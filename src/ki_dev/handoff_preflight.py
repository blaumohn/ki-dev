"""Deterministischer Vorlauf für die manuelle Review-Übergabe.

Datenfluss: CLI ruft ``load_preflight_config`` und ``run_preflight``
(beide mit Schreibwirkung: Prozessaufrufe, Prüfartefakt) auf und erhält
einen ``PreflightReport``; ``render_review_handoff`` ist reines
Rendering ohne I/O. Unabhängig von ``ki_dev.loop``/``loop_runtime``:
kein Checkpoint, kein Commit, keine Runden-/Sicherheitsgrenzen, keine
Agentensteuerung. Prozessaufrufe laufen ohne Shell in der
Projektwurzel; die Umgebung wird nicht eingeschränkt (geerbte
Umgebung des Aufrufers), das ist keine Vorgabe dieses Auftrags.

Der Vorlauf bindet den Bericht nicht an einen Quellstand: kein
Fingerprint, kein Git-Aufruf, keine Drifterkennung zwischen den
Prüfungen. Der Bericht nennt nur den Zeitpunkt; Bericht und
Arbeitsstand ordnet der Mensch einander zu und startet den Vorlauf
nach weiteren Änderungen erneut (docs/handoff.de.md).
"""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import shutil
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from plumbum import ProcessTimedOut, local
from plumbum.machines.local import LocalCommand

from ki_dev.handoff import HandoffIssue, Step, render_handoff

ARTIFACT_DIR = Path(".local/handoff/preflight")

_TABLE_KEYS = ("tool", "ki-dev", "handoff", "preflight")
_CONFIG_PATH = "tool.ki-dev.handoff.preflight"

# Ausgabegrenzen je Befehl: Ein Fehlschlag behält Anfang und Ende der
# Ausgabe, ein Erfolg nur die letzte Zeile (z. B. eine Testzusammen-
# fassung).
_MAX_FAILURE_DETAIL_CHARS = 1200
_MAX_SUCCESS_DETAIL_CHARS = 200
# name kommt aus der Projektkonfiguration, nicht aus Prozessausgabe,
# unterliegt im Bericht aber derselben Begrenzungs-/Bereinigungspflicht
# wie bounded_detail (kein voller Log, keine Steuerzeichen/ANSI-Codes
# im Agentenkontext). Beide Ausgabewege -- Prüfartefakt und
# Terminalausgabe -- verwenden dafür ``_report_name``. argv ist bereits
# beim Konfigurationsladen auf höchstens _MAX_COMMAND_CHARS begrenzt
# und wird vollständig gezeigt.
_MAX_COMMAND_CHARS = 100

_PATH_SEPARATORS = tuple(sep for sep in (os.sep, os.altsep) if sep)

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

Status = Literal["pass", "fail", "omitted"]


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
    """Ein Korrektur- oder Prüfbefehl aus der Projektkonfiguration."""

    name: str
    argv: tuple[str, ...]
    timeout_s: float


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


# Strukturregeln (Typen, Pflichtfelder, Listenformen) stehen als
# JSON Schema beim zuständigen Vertrag; geprüft werden die bereits
# geparsten TOML-Tabellen im Speicher. Unbekannte Felder bleiben
# bewusst erlaubt: Der Vorlauf liest eine fremde pyproject.toml und
# darf zusätzliche Projektangaben nicht zum Konfigurationsfehler
# machen.
_COMMAND_SCHEMA = {
    "type": "object",
    "required": ["name", "argv", "timeout_s"],
    "properties": {
        "name": {"type": "string", "minLength": 1, "pattern": r"\S"},
        "argv": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "minLength": 1},
        },
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
    raw = _read_preflight_table(project_root / "pyproject.toml")
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
        table: object = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise PreflightConfigError(
            f"{path} ist kein gültiges TOML: {exc}"
        ) from exc
    for key in _TABLE_KEYS:
        if not isinstance(table, dict) or key not in table:
            raise PreflightConfigError(
                f"{_CONFIG_PATH} fehlt in {path}"
            )
        table = table[key]
    return table


def _validate_structure(table: object) -> dict:
    if isinstance(table, dict) and "checks" not in table:
        raise PreflightConfigError(
            f"{_CONFIG_PATH}.checks fehlt; mindestens eine Prüfung ist "
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
    parts = [_CONFIG_PATH]
    for step in path:
        parts.append(
            f"[{step}]" if isinstance(step, int) else f".{step}"
        )
    return "".join(parts)


def _commands(
    raw: Iterable[dict], field: str
) -> tuple[CommandSpec, ...]:
    return tuple(
        _command(item, f"{_CONFIG_PATH}.{field}[{index}]")
        for index, item in enumerate(raw)
    )


def _command(item: dict, label: str) -> CommandSpec:
    """Einen bereits strukturgeprüften Eintrag abschließend prüfen.

    Ergänzend zum Schema, weil sich diese Regeln dort nicht oder nicht
    unterscheidbar ausdrücken lassen: Ein einzelnes ``pattern`` kann
    NUL und CR/LF nicht getrennt melden, die Befehlslänge gilt für
    ``shlex.join(argv)`` statt für ein einzelnes Feld, und
    ``exclusiveMinimum`` lässt ``inf``/``nan`` durch.
    """
    argv = tuple(item["argv"])
    _check_argv_characters(argv, label)
    _check_command_length(argv, label)
    timeout_s = float(item["timeout_s"])
    _check_timeout_finite(timeout_s, label)
    return CommandSpec(item["name"], argv, timeout_s)


def _check_argv_characters(argv: tuple[str, ...], label: str) -> None:
    joined = "".join(argv)
    if "\x00" in joined:
        raise PreflightConfigError(
            f"{label}.argv darf kein NUL-Zeichen enthalten"
        )
    if "\r" in joined or "\n" in joined:
        raise PreflightConfigError(
            f"{label}.argv darf kein Zeilenumbruchzeichen (CR/LF) "
            "enthalten"
        )


def _check_command_length(argv: tuple[str, ...], label: str) -> None:
    command = shlex.join(argv)
    if len(command) > _MAX_COMMAND_CHARS:
        raise PreflightConfigError(
            f"{label}.argv ergibt mit Quoting {len(command)} Zeichen, "
            f"erlaubt sind höchstens {_MAX_COMMAND_CHARS}: lange Logik "
            "gehört in ein benanntes Skript/Modul"
        )


def _check_timeout_finite(timeout_s: float, label: str) -> None:
    if not math.isfinite(timeout_s):
        raise PreflightConfigError(
            f"{label}.timeout_s muss endlich sein"
        )


def _check_unique_names(specs: tuple[CommandSpec, ...]) -> None:
    names = [spec.name for spec in specs]
    if len(names) != len(set(names)):
        raise PreflightConfigError(
            f"{_CONFIG_PATH}: name ist mehrfach vergeben"
        )


def run_preflight(
    config: PreflightConfig, project_root: Path
) -> PreflightReport:
    """Korrekturen seriell, dann Prüfungen, ohne Shell/Commit/Reset.

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
                )
            )
            continue
        result = _run_command(project_root, spec)
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
                )
            )
        return _finish(project_root, results, started_at, valid=False)

    checks_ok = True
    for spec in config.checks:
        result = _run_command(project_root, spec)
        results.append(result)
        if result.status != "pass":
            checks_ok = False
    return _finish(project_root, results, started_at, valid=checks_ok)


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
    report = PreflightReport(started_at, tuple(results), valid)
    _with_partial_results(
        results, _write_artifact, project_root, report
    )
    return report


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


def _bounded(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = limit // 2
    tail = limit - head
    omitted = len(text) - limit
    return (
        f"{text[:head]}\n[... {omitted} Zeichen ausgelassen ...]\n"
        f"{text[-tail:]}"
    )


def _report_name(name: str) -> str:
    """Name für den Bericht bereinigen und begrenzen.

    Gemeinsam für Prüfartefakt und Terminalausgabe, damit beide
    Ausgabewege dieselbe Aufbereitung verwenden.
    """
    return _bounded(_clean(name), _MAX_SUCCESS_DETAIL_CHARS)


def _write_artifact(
    project_root: Path, report: PreflightReport
) -> Path:
    directory = project_root / ARTIFACT_DIR
    payload = {
        "started_at": report.started_at,
        "valid": report.valid,
        "commands": [
            {
                "name": _report_name(item.name),
                "argv": list(item.argv),
                "status": item.status,
                "exit_code": item.exit_code,
                "detail": item.bounded_detail,
                "omitted": item.omitted,
            }
            for item in report.commands
        ],
    }
    try:
        directory.mkdir(parents=True, exist_ok=True)
        # Mikrosekunden, damit zwei Vorläufe in derselben Sekunde nicht
        # dasselbe Artefakt überschreiben.
        stamp = _utc_now().strftime("%Y%m%dT%H%M%S.%fZ")
        path = directory / f"{stamp}.json"
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        )
    except OSError as exc:
        raise PreflightExecutionError(
            f"Prüfartefakt nicht schreibbar: {exc}"
        ) from exc
    return path


def format_command_result(item: CommandResult) -> str:
    """Eine Zeile je Befehl: Name, Status, gekürztes Detail, argv.

    Gemeinsam für die Erfolgsübergabe (``render_review_handoff``) und
    den Reparaturbefund bei Fehlschlag genutzt, damit beide Pfade
    dieselben Angaben (einschließlich ausgelassener Befehle und der
    tatsächlichen argv) zeigen. name stammt aus der Konfiguration,
    nicht aus Prozessausgabe, wird über ``_report_name`` aber ebenso
    bereinigt und begrenzt wie bounded_detail: kein voller Log, keine
    Steuerzeichen/ANSI-Codes im Agentenkontext; das Prüfartefakt
    verwendet dieselbe Aufbereitung. argv dagegen bleibt unverändert:
    Sie ist beim
    Konfigurationsladen bereits auf höchstens _MAX_COMMAND_CHARS
    begrenzt und frei von CR/LF/NUL (siehe ``_parse_command``), und der
    Mensch soll den Befehl daraus wörtlich nachvollziehen und erneut
    starten können. Deshalb wird nichts still entfernt und nichts
    maskiert; ``shlex.join`` hält nur die Argumentgrenzen eindeutig.
    """
    name = _report_name(item.name)
    argv_text = shlex.join(item.argv)
    parts = [f"- {name}: {item.status.upper()}"]
    if item.bounded_detail:
        parts.append(item.bounded_detail)
    parts.append(f"[argv={argv_text}]")
    return " ".join(parts)


def render_review_handoff(
    issue: HandoffIssue, report: PreflightReport
) -> str:
    """Reines Rendering: hängt den kompakten Vorlaufbericht an die
    Review-Übergabe (``handoff.render_handoff``) an."""
    lines = [f"PRUEFBERICHT vorlauf-start={report.started_at}"]
    lines += [format_command_result(item) for item in report.commands]
    lines.append(
        "Hinweis: Der Zeitpunkt dient der manuellen Zuordnung, nicht "
        "als Beweis eines unveränderten Quellstands; nach weiteren "
        "Änderungen den Vorlauf erneut starten."
    )
    return render_handoff(issue, Step.REVIEW) + "\n".join(lines) + "\n"
