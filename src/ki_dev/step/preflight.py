"""Deterministischer Vorlauf für die manuelle Review-Übergabe.

Datenfluss: CLI ruft ``load_preflight_config`` und ``run_preflight``
(beide mit Schreibwirkung: Prozessaufrufe, Prüfartefakt) auf und erhält
einen ``PreflightReport``; ``render_review_handoff`` ist reines
Rendering ohne I/O. Unabhängig von ``ki_dev.runner``:
kein Checkpoint, kein Commit, keine Runden-/Sicherheitsgrenzen, keine
Agentensteuerung. Prozessaufrufe laufen ohne Shell in der
Projektwurzel; die Umgebung wird nicht eingeschränkt (geerbte
Umgebung des Aufrufers), das ist keine Vorgabe dieses Auftrags.

Der Vorlauf bindet den Bericht nicht an einen Quellstand: kein
Fingerprint, kein Git-Aufruf, keine Drifterkennung zwischen den
Prüfungen. Der Bericht nennt nur den Zeitpunkt; Bericht und
Arbeitsstand ordnet der Mensch einander zu und startet den Vorlauf
nach weiteren Änderungen erneut (docs/step.de.md).
"""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import shutil
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from plumbum import ProcessTimedOut, local
from plumbum.machines.local import LocalCommand

from ki_dev.config_sources import ConfigSource
from ki_dev.flow.planning import PlanningFlow
from ki_dev.step.contract import Step
from ki_dev.step.guidelines import (
    GuidelineSection,
    render_guideline_block,
)
from ki_dev.step.handoff import HandoffIssue, render_base_handoff

ARTIFACT_DIR = Path(".local/handoff/preflight")

# Ort der Vorlauf-Konfiguration; maßgeblich für Laden, Fehlbefund und
# Auflistung (ki-dev config).
CONFIG_FILE = Path("pyproject.toml")
CONFIG_TABLE = "tool.ki-dev.handoff.preflight"
_TABLE_KEYS = tuple(CONFIG_TABLE.split("."))
CONFIG_SOURCE = ConfigSource(
    "handoff --step review", str(CONFIG_FILE), CONFIG_TABLE, CONFIG_FILE
)

# Ausgabegrenzen je Befehl: Ein Fehlschlag behält Anfang und Ende der
# Ausgabe, ein Erfolg nur die letzte Zeile (z. B. eine Testzusammen-
# fassung).
_MAX_FAILURE_DETAIL_CHARS = 1200
_MAX_SUCCESS_DETAIL_CHARS = 200
# name kommt aus der Projektkonfiguration, nicht aus Prozessausgabe,
# unterliegt im Bericht aber derselben Begrenzungs-/Bereinigungspflicht
# wie bounded_detail (kein voller Log, keine Steuerzeichen/ANSI-Codes
# im Agentenkontext). Beide Ausgabewege -- Prüfartefakt und
# Terminalausgabe -- verwenden dafür ``report_name``. argv selbst ist
# nicht in der Länge begrenzt: Das Prüfartefakt enthält sie vollständig,
# Übergabe und Reparaturbefund zeigen sie einzeilig gekürzt und
# verweisen einmal auf das Artefakt (``artifact_line``).
_MAX_ARGV_DISPLAY_CHARS = 100
# Steht nie gekürzt neben argv, damit eine Abwahl per --preflight-args
# auch bei gekürzter argv sichtbar bleibt.
ADDED_MARKER = "[ergänzt per --preflight-args]"
# Teillauf: Zusatzargumente oder ausgelassene Prüfungen. Gilt für
# Erst-Review und Folgerunde; ein PASS braucht den vollen Vorlauf.
PARTIAL_RUN_NOTE = (
    "TEILLAUF: Zusatzargumente oder ausgelassene Prüfungen (siehe "
    "Bericht). Abweichend von der Rolle ist PASS ausgeschlossen; "
    "Ausgabe: CHANGES | NEEDS_DECISION. PASS erst nach einem "
    "vollständigen Vorlauf ohne --preflight-args/--preflight-skip."
)

_PATH_SEPARATORS = tuple(sep for sep in (os.sep, os.altsep) if sep)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

Status = Literal["pass", "fail", "omitted", "skipped"]


class PreflightConfigError(ValueError):
    """Aufruf/Bead/Konfiguration ungültig; keine Schreibwirkung."""


class PreflightExecutionError(RuntimeError):
    """Vorlauf konnte nicht kontrolliert abgeschlossen werden.

    Artefaktfehler, die keinem einzelnen konfigurierten Befehl
    zuzuordnen sind; führt nie zu einer Übergabe.
    ``partial_results`` trägt die bis zum Fehler bereits gelaufenen
    Befehle (auch bestandene, nicht zurückgesetzte Korrekturen), damit
    sie trotz des Fehlers sichtbar bleiben statt verworfen zu werden.
    """

    def __init__(
        self,
        message: str,
        partial_results: tuple[CommandResult, ...] = (),
    ) -> None:
        super().__init__(message)
        self.partial_results = partial_results


@dataclass(frozen=True)
class CommandSpec:
    """Ein Korrektur- oder Prüfbefehl aus der Projektkonfiguration.

    ``added`` nennt die per ``--preflight-args`` an ``argv``
    angehängten Argumente (bereits in ``argv`` enthalten); leer ohne
    Ergänzung. ``skip_reason`` ist der Grund aus ``--preflight-skip``;
    eine Prüfung mit Grund startet nicht.
    """

    name: str
    argv: tuple[str, ...]
    timeout_s: float
    added: tuple[str, ...] = ()
    skip_reason: str | None = None


@dataclass(frozen=True)
class PreflightConfig:
    corrections: tuple[CommandSpec, ...]
    checks: tuple[CommandSpec, ...]


@dataclass(frozen=True)
class CommandResult:
    name: str
    argv: tuple[str, ...]
    status: Status
    exit_code: int | None
    bounded_detail: str
    omitted: bool
    added: tuple[str, ...] = ()
    skip_reason: str | None = None


@dataclass(frozen=True)
class PreflightReport:
    """``valid`` heißt: Grundlage für eine erfolgreiche Review-Übergabe.

    ``started_at`` nennt den Beginn des Vorlaufs zur manuellen
    Zuordnung. Es ist keine Bindung an einen Quellstand: Der Vorlauf
    erfasst weder Fingerprints noch Git-Stände und erkennt keine
    Änderungen zwischen Prüfungen. Diese Zuordnung verantwortet der
    Mensch, der den Vorlauf nach weiteren Änderungen erneut startet.
    """

    started_at: str
    commands: tuple[CommandResult, ...]
    valid: bool
    artifact: Path

    @property
    def partial(self) -> bool:
        """Teillauf: Zusatzargumente oder ausgelassene Prüfungen.

        Unabhängig von ``valid`` (Übergabefähigkeit): Ein bestandener
        Teillauf erlaubt ein Zwischenreview, aber keinen PASS.
        """
        return is_partial(self.commands)


def is_partial(commands: Iterable[CommandResult]) -> bool:
    """Gemeinsame Teillauf-Regel für Bericht und Prüfartefakt."""
    return any(
        item.added or item.status == "skipped" for item in commands
    )


# Strukturregeln (Typen, Pflichtfelder, Listenformen) stehen als
# JSON Schema beim zuständigen Vertrag; geprüft werden die bereits
# geparsten TOML-Tabellen im Speicher. Unbekannte Felder bleiben
# bewusst erlaubt: Der Vorlauf liest eine fremde pyproject.toml und
# darf zusätzliche Projektangaben nicht zum Konfigurationsfehler
# machen.
# Gemeinsame Regel für argv aus der Konfiguration und für per
# --preflight-args ergänzte Argumente (preflight_options).
ARGV_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "items": {"type": "string", "minLength": 1},
}

_COMMAND_SCHEMA = {
    "type": "object",
    "required": ["name", "argv", "timeout_s"],
    "properties": {
        "name": {"type": "string", "minLength": 1, "pattern": r"\S"},
        "argv": ARGV_SCHEMA,
        "timeout_s": {"type": "number", "exclusiveMinimum": 0},
    },
}

_PREFLIGHT_SCHEMA = {
    "type": "object",
    "required": ["checks"],
    "properties": {
        "corrections": {"type": "array", "items": _COMMAND_SCHEMA},
        "checks": {
            "type": "array",
            "minItems": 1,
            "items": _COMMAND_SCHEMA,
        },
    },
}

# Bereinigte Diagnose je Schemaregel: Der Text stammt aus dem Schema,
# nie aus der gelesenen Konfiguration; Rohwerte erscheinen nicht.
_RULE_DIAGNOSES = {
    "minItems": "ist leer",
    "minLength": "ist leer",
    "pattern": "enthält nur Leerraum",
    "exclusiveMinimum": "muss größer als 0 sein",
}


def load_preflight_config(project_root: Path) -> PreflightConfig:
    """Lies ``tool.ki-dev.handoff.preflight`` aus ``pyproject.toml``.

    Keine Autodetektion und keine automatische Installation: Fehlt die
    Tabelle oder ``checks``, ist das ein Konfigurationsfehler, kein
    Anlass für einen automatischen Modellstart.
    """
    raw = _read_preflight_table(project_root / CONFIG_FILE)
    table = _validate_structure(raw)
    corrections = _commands(table.get("corrections", ()), "corrections")
    checks = _commands(table["checks"], "checks")
    _check_unique_names((*corrections, *checks))
    return PreflightConfig(corrections=corrections, checks=checks)


def _read_preflight_table(path: Path) -> object:
    """Die Tabelle im Dokument finden; ihr Inhalt wird nicht geprüft.

    Das ist reines Nachschlagen der Fundstelle, keine Validierung: Der
    Datenvertrag der gefundenen Tabelle steht im Schema.
    """
    table: object = read_toml(path)
    for key in _TABLE_KEYS:
        if not isinstance(table, dict) or key not in table:
            raise PreflightConfigError(
                f"{CONFIG_TABLE} fehlt in {path}"
            )
        table = table[key]
    return table


def read_toml(path: Path) -> object:
    """TOML-Datei lesen; Lese-, UTF-8- und Syntaxfehler als
    ``PreflightConfigError``. Gemeinsam mit ``--next-turn``."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PreflightConfigError(
            f"{path} nicht lesbar: {exc}"
        ) from exc
    except UnicodeDecodeError as exc:
        raise PreflightConfigError(
            f"{path} ist nicht als UTF-8 lesbar: {exc}"
        ) from exc
    try:
        return tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise PreflightConfigError(
            f"{path} ist kein gültiges TOML: {exc}"
        ) from exc


def _validate_structure(table: object) -> dict:
    if isinstance(table, dict) and "checks" not in table:
        raise PreflightConfigError(
            f"{CONFIG_TABLE}.checks fehlt; mindestens eine Prüfung ist "
            "für eine erfolgreiche Review-Übergabe erforderlich"
        )
    try:
        Draft202012Validator(_PREFLIGHT_SCHEMA).validate(table)
    except ValidationError as exc:
        raise PreflightConfigError(_diagnosis(exc)) from exc
    # ``type: object`` im Schema hat den Typ bereits erzwungen; hier
    # wird er nicht erneut geprüft, nur zugesichert.
    return cast(dict, table)


def _diagnosis(error: ValidationError) -> str:
    """Validierungsfehler in eine Diagnose mit Feldpfad übersetzen."""
    field = _field_path(error.absolute_path)
    if error.validator == "required":
        missing = ", ".join(
            key
            for key in error.validator_value
            if key not in error.instance
        )
        return f"{field}: Pflichtfeld fehlt: {missing}"
    if error.validator == "type":
        return f"{field}: muss vom Typ {error.validator_value} sein"
    # Auffangtext für Schemaregeln, die erst später hinzukommen: Der
    # Fehler bleibt sichtbar, nur die Regelbeschreibung fehlt dann.
    rule = _RULE_DIAGNOSES.get(str(error.validator), "ist ungültig")
    return f"{field}: {rule}"


def _field_path(path: Iterable[str | int]) -> str:
    parts = [CONFIG_TABLE]
    for step in path:
        parts.append(
            f"[{step}]" if isinstance(step, int) else f".{step}"
        )
    return "".join(parts)


def _commands(
    raw: Iterable[dict], field: str
) -> tuple[CommandSpec, ...]:
    return tuple(
        _command(item, f"{CONFIG_TABLE}.{field}[{index}]")
        for index, item in enumerate(raw)
    )


def _command(item: dict, label: str) -> CommandSpec:
    """Einen bereits strukturgeprüften Eintrag abschließend prüfen.

    Ergänzend zum Schema, weil sich diese Regeln dort nicht oder nicht
    unterscheidbar ausdrücken lassen: Ein einzelnes ``pattern`` kann
    NUL und CR/LF nicht getrennt melden, und ``exclusiveMinimum`` lässt
    ``inf``/``nan`` durch. Die Länge von argv ist nicht begrenzt.
    """
    argv = tuple(item["argv"])
    problem = argv_character_problem(argv)
    if problem:
        raise PreflightConfigError(f"{label}.argv {problem}")
    timeout_s = float(item["timeout_s"])
    _check_timeout_finite(timeout_s, label)
    return CommandSpec(item["name"], argv, timeout_s)


def argv_character_problem(argv: Sequence[str]) -> str | None:
    """Zeichenregel für argv; ``None`` heißt zulässig."""
    joined = "".join(argv)
    if "\x00" in joined:
        return "darf kein NUL-Zeichen enthalten"
    if "\r" in joined or "\n" in joined:
        return "darf kein Zeilenumbruchzeichen (CR/LF) enthalten"
    return None


def _check_timeout_finite(timeout_s: float, label: str) -> None:
    if not math.isfinite(timeout_s):
        raise PreflightConfigError(
            f"{label}.timeout_s muss endlich sein"
        )


def _check_unique_names(specs: tuple[CommandSpec, ...]) -> None:
    names = [spec.name for spec in specs]
    if len(names) != len(set(names)):
        raise PreflightConfigError(
            f"{CONFIG_TABLE}: name ist mehrfach vergeben"
        )


def run_preflight(
    config: PreflightConfig,
    project_root: Path,
    on_start: Callable[[str], None] | None = None,
) -> PreflightReport:
    """Korrekturen seriell, dann Prüfungen, ohne Shell/Commit/Reset.

    ``on_start`` erhält vor jedem gestarteten Befehl eine bereinigte
    Fortschrittszeile (``progress_line``); ausgelassene Befehle melden
    keinen Start. Die Ausgabe selbst bleibt Sache des Aufrufers.

    Bricht bei der ersten fehlgeschlagenen Korrektur ab; bereits
    erfolgte Änderungen bleiben stehen (kein automatischer Rückbau).
    Restliche Korrekturen gelten dann als ausgelassen, Prüfungen
    laufen in diesem Fall nicht. Der Vorlauf vergleicht keinen
    Quellstand vor und nach den Prüfungen: Dass der Arbeitsstand
    währenddessen unverändert bleibt, hält der Mensch ein, der den
    Vorlauf nach weiteren Änderungen erneut startet.
    """
    started_at = _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")
    results: list[CommandResult] = []
    corrections_ok = True
    for spec in config.corrections:
        if not corrections_ok:
            results.append(
                CommandResult(
                    spec.name,
                    spec.argv,
                    "omitted",
                    None,
                    "ausgelassen: vorherige Korrektur fehlgeschlagen",
                    omitted=True,
                    added=spec.added,
                )
            )
            continue
        result = _run_started(project_root, spec, on_start)
        results.append(result)
        if result.status != "pass":
            corrections_ok = False

    if not corrections_ok:
        for spec in config.checks:
            results.append(
                CommandResult(
                    spec.name,
                    spec.argv,
                    "omitted",
                    None,
                    "ausgelassen: Korrektur fehlgeschlagen, Prüfung "
                    "nicht gestartet",
                    omitted=True,
                    added=spec.added,
                )
            )
        return _finish(project_root, results, started_at, valid=False)

    checks_ok = True
    for spec in config.checks:
        if spec.skip_reason is not None:
            results.append(_skipped(spec))
            continue
        result = _run_started(project_root, spec, on_start)
        results.append(result)
        if result.status != "pass":
            checks_ok = False
    return _finish(project_root, results, started_at, valid=checks_ok)


def _skipped(spec: CommandSpec) -> CommandResult:
    """Per --preflight-skip ausgelassene Prüfung; startet nicht."""
    return CommandResult(
        spec.name,
        spec.argv,
        "skipped",
        None,
        f"ausgelassen per --preflight-skip: {spec.skip_reason}",
        omitted=True,
        added=spec.added,
        skip_reason=spec.skip_reason,
    )


def progress_line(spec: CommandSpec) -> str:
    """Fortschrittszeile für einen gestarteten Befehl."""
    return (
        f"Vorlauf: {report_name(spec.name)} läuft "
        f"(Timeout {spec.timeout_s:g} s) …"
    )


def _run_started(
    project_root: Path,
    spec: CommandSpec,
    on_start: Callable[[str], None] | None,
) -> CommandResult:
    if on_start is not None:
        on_start(progress_line(spec))
    return _run_command(project_root, spec)


def _with_partial_results(results: list[CommandResult], func, *args):
    """Ruft ``func`` auf; hängt bereits gelaufene Befehle an einen
    ``PreflightExecutionError`` an, statt sie mit ihm zu verwerfen."""
    try:
        return func(*args)
    except PreflightExecutionError as exc:
        raise PreflightExecutionError(
            str(exc), partial_results=tuple(results)
        ) from exc


def _finish(
    project_root: Path,
    results: list[CommandResult],
    started_at: str,
    *,
    valid: bool,
) -> PreflightReport:
    commands = tuple(results)
    artifact = _with_partial_results(
        results,
        _write_artifact,
        project_root,
        started_at,
        commands,
        valid,
    )
    return PreflightReport(started_at, commands, valid, artifact)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _run_command(
    project_root: Path, spec: CommandSpec
) -> CommandResult:
    """Einen Befehl ohne Shell in der Projektwurzel ausführen.

    Startfehler, Timeout und fehlerhafter Exitstatus bleiben
    unterscheidbar; die Prozessausgabe geht nur bereinigt und begrenzt
    in die Diagnose. Plumbum dekodiert sie als UTF-8 und verwirft
    ungültige Bytes, statt sie zu ersetzen -- für eine bereits
    gekürzte Diagnose ist das gleichwertig.

    ``env`` wird ausdrücklich übergeben, weil Plumbum sonst nur seine
    beim Import erstellte Kopie von ``os.environ`` weiterreicht; der
    Vorlauf schränkt die Umgebung aber nicht ein. Plumbum legt die
    übergebene Umgebung über die Kopie, sodass eine nach dem Import
    gelöschte Variable sichtbar bliebe. Für den einmaligen CLI-Aufruf,
    den der Vorlauf bedient, fallen Import- und Startzeitpunkt
    zusammen; dafür wird keine weitere Umgebungsverwaltung gebaut. Die
    Programmsuche in ``_program`` liest ``os.environ`` ohnehin direkt.
    """
    program = _program(project_root, spec.argv[0])
    if program is None:
        return _start_failure(
            spec, f"{spec.argv[0]} nicht im PATH gefunden"
        )
    try:
        exit_code, stdout, stderr = program.run(
            spec.argv[1:],
            retcode=None,
            timeout=spec.timeout_s,
            cwd=project_root,
            env=os.environ,
        )
    except ProcessTimedOut:
        return CommandResult(
            spec.name,
            spec.argv,
            "fail",
            None,
            f"Timeout nach {spec.timeout_s:g} s",
            omitted=False,
            added=spec.added,
        )
    except OSError as exc:
        return _start_failure(spec, str(exc))
    return CommandResult(
        spec.name,
        spec.argv,
        "pass" if exit_code == 0 else "fail",
        exit_code,
        _exit_detail(exit_code, stdout + stderr),
        omitted=False,
        added=spec.added,
    )


def _program(project_root: Path, program: str) -> LocalCommand | None:
    """argv[0] wie ``execvp`` auflösen; ``None`` heißt nicht gefunden.

    Enthält der Name einen Pfadtrenner, gilt er relativ zum
    Arbeitsverzeichnis des Befehls -- Plumbum löst relative
    Programmpfade sonst gegen das Arbeitsverzeichnis des Aufrufers
    auf, und ``scripts/pruefe.sh`` (die vom Vorlaufvertrag für längere
    Logik vorgesehene Form) wäre je nach Startort ein Startfehler.

    Ein Name ohne Trenner wird im aktuellen ``PATH`` gesucht, exakt
    und selbst: ``local[name]`` würde zu ``pruef_werkzeug``
    ersatzweise auch ``pruef-werkzeug`` und ``pruef.werkzeug``
    starten, also einen anderen als den konfigurierten Befehl.
    """
    if any(sep in program for sep in _PATH_SEPARATORS):
        return local[str(project_root / program)]
    resolved = shutil.which(program, path=os.environ.get("PATH"))
    return None if resolved is None else local[resolved]


def _start_failure(spec: CommandSpec, reason: str) -> CommandResult:
    return CommandResult(
        spec.name,
        spec.argv,
        "fail",
        None,
        _bounded(f"Startfehler: {reason}", _MAX_FAILURE_DETAIL_CHARS),
        omitted=False,
        added=spec.added,
    )


def _clean(text: str) -> str:
    return _CONTROL_CHARS.sub("", _ANSI_ESCAPE.sub("", text))


def _exit_detail(returncode: int, output: str) -> str:
    text = _clean(output).strip()
    if returncode == 0:
        lines = text.splitlines()
        last = lines[-1] if lines else ""
        omitted = len(text) - len(last)
        detail = _bounded(last, _MAX_SUCCESS_DETAIL_CHARS)
        marker = f" [{omitted} Zeichen Ausgabe ausgelassen]"
        return detail + (marker if omitted else "")
    return f"exit={returncode}\n" + _bounded(
        text, _MAX_FAILURE_DETAIL_CHARS
    )


def _bounded(text: str, limit: int, *, inline: bool = False) -> str:
    """Anfang und Ende behalten, die Auslassung sichtbar markieren.

    ``inline`` hält das Ergebnis einzeilig (für argv im Bericht);
    sonst steht die Markierung auf eigener Zeile (Prozessausgabe).
    """
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    omitted = len(text) - limit
    if inline:
        return f"{text[:head]}…(+{omitted})…{text[-tail:]}"
    return (
        f"{text[:head]}\n[... {omitted} Zeichen ausgelassen ...]\n"
        f"{text[-tail:]}"
    )


def report_name(name: str) -> str:
    """Name für den Bericht bereinigen und begrenzen.

    Gemeinsam für Prüfartefakt und Terminalausgabe, damit beide
    Ausgabewege dieselbe Aufbereitung verwenden.
    """
    return _bounded(_clean(name), _MAX_SUCCESS_DETAIL_CHARS)


def _write_artifact(
    project_root: Path,
    started_at: str,
    commands: tuple[CommandResult, ...],
    valid: bool,
) -> Path:
    """Bericht mit vollständiger argv ablegen; Pfad relativ zur
    Projektwurzel zurückgeben (so erscheint er in der Ausgabe)."""
    directory = project_root / ARTIFACT_DIR
    payload = {
        "started_at": started_at,
        "valid": valid,
        "partial": is_partial(commands),
        "commands": [
            {
                "name": report_name(item.name),
                "argv": list(item.argv),
                "status": item.status,
                "exit_code": item.exit_code,
                "detail": item.bounded_detail,
                "omitted": item.omitted,
                "added_args": list(item.added),
                "skip_reason": item.skip_reason,
            }
            for item in commands
        ],
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # Mikrosekunden, damit zwei Vorläufe in derselben Sekunde nicht
        # dasselbe Artefakt überschreiben.
        stamp = _utc_now().strftime("%Y%m%dT%H%M%S.%fZ")
        name = f"{stamp}.json"
        (directory / name).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        )
    except OSError as exc:
        raise PreflightExecutionError(
            f"Prüfartefakt nicht schreibbar: {exc}"
        ) from exc
    return ARTIFACT_DIR / name


def format_command_result(item: CommandResult) -> str:
    """Eine Zeile je Befehl: Name, Status, gekürztes Detail, argv.

    Gemeinsam für die Erfolgsübergabe (``render_review_handoff``) und
    den Reparaturbefund bei Fehlschlag genutzt, damit beide Pfade
    dieselben Angaben (einschließlich ausgelassener Befehle und der
    tatsächlichen argv) zeigen. name stammt aus der Konfiguration,
    nicht aus Prozessausgabe, wird über ``report_name`` aber ebenso
    bereinigt und begrenzt wie bounded_detail: kein voller Log, keine
    Steuerzeichen/ANSI-Codes im Agentenkontext; das Prüfartefakt
    verwendet dieselbe Aufbereitung. argv ist frei von CR/LF/NUL (siehe
    ``_command``) und wird nicht maskiert; ``shlex.join`` hält die
    Argumentgrenzen eindeutig. Lange argv werden sichtbar gekürzt
    (``…(+N)…``); vollständig stehen sie im Prüfartefakt, auf das
    ``artifact_line`` einmal je Ausgabe verweist.
    """
    name = report_name(item.name)
    argv_text = _bounded(
        shlex.join(item.argv), _MAX_ARGV_DISPLAY_CHARS, inline=True
    )
    parts = [f"- {name}: {item.status.upper()}"]
    if item.bounded_detail:
        parts.append(item.bounded_detail)
    parts.append(f"[argv={argv_text}]")
    if item.added:
        parts.append(ADDED_MARKER)
    return " ".join(parts)


def render_review_handoff(
    issue: HandoffIssue,
    report: PreflightReport,
    guidelines: Sequence[GuidelineSection] = (),
    *,
    flow: PlanningFlow,
) -> str:
    """Reines Rendering: Basis-Review-Übergabe, kompakter
    Vorlaufbericht, danach der gesonderte Leitlinienblock."""
    lines = render_report_lines(report)
    return (
        render_base_handoff(issue, Step.REVIEW, flow=flow)
        + "\n".join(lines)
        + "\n"
        + render_guideline_block(guidelines)
    )


def render_report_lines(report: PreflightReport) -> list[str]:
    """Kompakter Vorlaufbericht (``PRUEFBERICHT …``) als Zeilen;
    gemeinsam für Review-Übergabe und ``--next-turn``."""
    lines = [f"PRUEFBERICHT vorlauf-start={report.started_at}"]
    lines += [format_command_result(item) for item in report.commands]
    lines.append(artifact_line(report))
    if report.partial:
        lines.append(PARTIAL_RUN_NOTE)
    lines.append(
        "Hinweis: Der Zeitpunkt dient der manuellen Zuordnung, nicht "
        "als Beweis eines unveränderten Quellstands; nach weiteren "
        "Änderungen den Vorlauf erneut starten."
    )
    return lines


def artifact_line(report: PreflightReport) -> str:
    """Einziger Verweis je Ausgabe auf den vollständigen Bericht."""
    return f"Vollständig: {report.artifact}"
