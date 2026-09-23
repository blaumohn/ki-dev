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
import re
import shlex
import subprocess
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from ki_dev.handoff import HandoffIssue, Step, render_handoff

ARTIFACT_DIR = Path(".local/handoff/preflight")

_TABLE_KEYS = ("tool", "ki-dev", "handoff", "preflight")

# Ausgabegrenzen je Befehl: Ein Fehlschlag behält Anfang und Ende der
# Ausgabe, ein Erfolg nur die letzte Zeile (z. B. eine Testzusammen-
# fassung).
_MAX_FAILURE_DETAIL_CHARS = 1200
_MAX_SUCCESS_DETAIL_CHARS = 200
# name kommt aus der Projektkonfiguration, nicht aus Prozessausgabe,
# unterliegt im Bericht aber derselben Begrenzungs-/Bereinigungspflicht
# wie bounded_detail (kein voller Log, keine Steuerzeichen/ANSI-Codes
# im Agentenkontext). argv ist bereits beim Konfigurationsladen auf
# höchstens _MAX_COMMAND_CHARS begrenzt und wird vollständig gezeigt.
_MAX_COMMAND_CHARS = 100

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


def load_preflight_config(project_root: Path) -> PreflightConfig:
    """Lies ``tool.ki-dev.handoff.preflight`` aus ``pyproject.toml``.

    Keine Autodetektion und keine automatische Installation: Fehlt die
    Tabelle oder ``checks``, ist das ein Konfigurationsfehler, kein
    Anlass für einen automatischen Modellstart.
    """
    path = project_root / "pyproject.toml"
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
        data: object = tomllib.loads(raw)
    except tomllib.TOMLDecodeError as exc:
        raise PreflightConfigError(
            f"{path} ist kein gültiges TOML: {exc}"
        ) from exc
    table: object = data
    for key in _TABLE_KEYS:
        if not isinstance(table, dict) or key not in table:
            raise PreflightConfigError(
                f"tool.ki-dev.handoff.preflight fehlt in {path}"
            )
        table = table[key]
    if not isinstance(table, dict):
        raise PreflightConfigError(
            "tool.ki-dev.handoff.preflight muss eine Tabelle sein"
        )
    corrections = _parse_commands(
        table.get("corrections", []), "corrections"
    )
    if "checks" not in table:
        raise PreflightConfigError(
            "tool.ki-dev.handoff.preflight.checks fehlt; mindestens "
            "eine Prüfung ist für eine erfolgreiche Review-Übergabe "
            "erforderlich"
        )
    checks = _parse_commands(table["checks"], "checks")
    if not checks:
        raise PreflightConfigError(
            "tool.ki-dev.handoff.preflight.checks ist leer; "
            "mindestens eine Prüfung ist erforderlich"
        )
    names = [item.name for item in (*corrections, *checks)]
    if len(names) != len(set(names)):
        raise PreflightConfigError(
            "tool.ki-dev.handoff.preflight: name ist mehrfach vergeben"
        )
    return PreflightConfig(corrections=corrections, checks=checks)


def _parse_commands(raw: object, field: str) -> tuple[CommandSpec, ...]:
    if not isinstance(raw, list):
        raise PreflightConfigError(
            f"tool.ki-dev.handoff.preflight.{field} muss eine Liste "
            "sein"
        )
    specs: list[CommandSpec] = []
    for index, item in enumerate(raw):
        specs.append(_parse_command(item, f"{field}[{index}]"))
    return tuple(specs)


def _parse_command(item: object, label: str) -> CommandSpec:
    if not isinstance(item, dict):
        raise PreflightConfigError(f"{label} muss eine Tabelle sein")
    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        raise PreflightConfigError(f"{label}.name fehlt oder ist leer")
    argv = item.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(part, str) and part for part in argv)
    ):
        raise PreflightConfigError(
            f"{label}.argv muss eine nichtleere Liste nichtleerer "
            "Zeichenketten sein"
        )
    if any(char in part for part in argv for char in "\x00\r\n"):
        raise PreflightConfigError(
            f"{label}.argv darf kein NUL- oder Zeilenumbruchzeichen "
            "(CR/LF) enthalten"
        )
    command = shlex.join(argv)
    if len(command) > _MAX_COMMAND_CHARS:
        raise PreflightConfigError(
            f"{label}.argv ergibt mit Quoting {len(command)} Zeichen, "
            f"erlaubt sind höchstens {_MAX_COMMAND_CHARS}: lange Logik "
            "gehört in ein benanntes Skript/Modul"
        )
    timeout_s = item.get("timeout_s")
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, (int, float))
        or not (0 < timeout_s < float("inf"))
    ):
        raise PreflightConfigError(
            f"{label}.timeout_s muss positiv und endlich sein"
        )
    return CommandSpec(name, tuple(argv), float(timeout_s))


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
    try:
        completed = subprocess.run(
            spec.argv,
            cwd=project_root,
            text=True,
            capture_output=True,
            errors="replace",
            timeout=spec.timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            spec.name,
            spec.argv,
            "fail",
            None,
            f"Timeout nach {spec.timeout_s:g} s",
            omitted=False,
        )
    except OSError as exc:
        return CommandResult(
            spec.name,
            spec.argv,
            "fail",
            None,
            _bounded(f"Startfehler: {exc}", _MAX_FAILURE_DETAIL_CHARS),
            omitted=False,
        )
    passed = completed.returncode == 0
    return CommandResult(
        spec.name,
        spec.argv,
        "pass" if passed else "fail",
        completed.returncode,
        _exit_detail(
            completed.returncode, completed.stdout + completed.stderr
        ),
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


def _write_artifact(
    project_root: Path, report: PreflightReport
) -> Path:
    directory = project_root / ARTIFACT_DIR
    payload = {
        "started_at": report.started_at,
        "valid": report.valid,
        "commands": [
            {
                "name": item.name,
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
    nicht aus Prozessausgabe, wird aber ebenso bereinigt und begrenzt
    wie bounded_detail: kein voller Log, keine Steuerzeichen/ANSI-Codes
    im Agentenkontext. argv dagegen bleibt unverändert: Sie ist beim
    Konfigurationsladen bereits auf höchstens _MAX_COMMAND_CHARS
    begrenzt und frei von CR/LF/NUL (siehe ``_parse_command``), und der
    Mensch soll den Befehl daraus wörtlich nachvollziehen und erneut
    starten können. Deshalb wird nichts still entfernt und nichts
    maskiert; ``shlex.join`` hält nur die Argumentgrenzen eindeutig.
    """
    name = _bounded(_clean(item.name), _MAX_SUCCESS_DETAIL_CHARS)
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
