"""Deterministischer Vorlauf für die manuelle Review-Übergabe.

Datenfluss: CLI ruft ``load_preflight_config`` und ``run_preflight``
(beide mit Schreibwirkung: Prozessaufrufe, Prüfartefakt) auf und erhält
einen ``PreflightReport``; ``render_review_handoff`` ist reines
Rendering ohne I/O. Unabhängig von ``ki_dev.loop``/``loop_runtime``:
kein Checkpoint, kein Commit, keine Runden-/Sicherheitsgrenzen, keine
Agentensteuerung. Prozessaufrufe laufen ohne Shell in der
Projektwurzel; die Umgebung wird nicht eingeschränkt (geerbte
Umgebung des Aufrufers), das ist keine Vorgabe dieses Auftrags.
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
import time
import tomllib
from dataclasses import dataclass
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
# name/argv kommen aus der Projektkonfiguration, nicht aus Prozess-
# ausgabe, unterliegen im Bericht aber derselben Begrenzungs-/
# Bereinigungspflicht wie bounded_detail (kein voller Log, keine
# Steuerzeichen/ANSI-Codes im Agentenkontext).
_MAX_ARGV_CHARS = 300

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# Eigenes Prüfartefakt dieses Vorlaufs: vom Fingerprint ausgeschlossen,
# sonst würde das Schreiben des Berichts den geprüften Stand selbst
# verändern.
_FINGERPRINT_EXCLUDES = (str(ARTIFACT_DIR),)

Status = Literal["pass", "fail", "omitted"]


class PreflightConfigError(ValueError):
    """Aufruf/Bead/Konfiguration ungültig; keine Schreibwirkung."""


class PreflightExecutionError(RuntimeError):
    """Vorlauf konnte nicht kontrolliert abgeschlossen werden.

    Git- oder Artefaktfehler, die keinem einzelnen konfigurierten
    Befehl zuzuordnen sind; führt nie zu einer Übergabe.
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

    ``source_fingerprint`` bindet den Bericht an den Quellstand nach
    den Korrekturen (auf dem die Prüfungen liefen).
    """

    source_fingerprint: str
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
        raw = path.read_text()
    except OSError as exc:
        raise PreflightConfigError(
            f"{path} nicht lesbar: {exc}"
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
    if any("\x00" in part for part in argv):
        raise PreflightConfigError(
            f"{label}.argv darf kein NUL-Zeichen enthalten"
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
    laufen in diesem Fall nicht. Der Fingerprint vor und nach den
    Prüfungen wird verglichen; eine Abweichung macht den Bericht
    ungültig, auch wenn alle Prüfungen für sich bestanden haben.
    """
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
        return _finish(project_root, results, valid=False)

    fingerprint_before_checks = _with_partial_results(
        results, _fingerprint, project_root
    )
    checks_ok = True
    for spec in config.checks:
        result = _run_command(project_root, spec)
        results.append(result)
        if result.status != "pass":
            checks_ok = False
    fingerprint_after_checks = _with_partial_results(
        results, _fingerprint, project_root
    )
    stable = fingerprint_before_checks == fingerprint_after_checks
    return _finish(
        project_root,
        results,
        valid=checks_ok and stable,
        fingerprint=fingerprint_before_checks,
    )


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
    *,
    valid: bool,
    fingerprint: str | None = None,
) -> PreflightReport:
    resolved_fingerprint = (
        fingerprint
        if fingerprint is not None
        else _with_partial_results(results, _fingerprint, project_root)
    )
    report = PreflightReport(
        resolved_fingerprint, tuple(results), valid
    )
    _with_partial_results(
        results, _write_artifact, project_root, report
    )
    return report


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


def _fingerprint(project_root: Path) -> str:
    """Bindet den Bericht an den tatsächlichen Quellstand inklusive
    uncommitteter Änderungen; Git-HEAD allein reicht bei verändertem
    Arbeitsbaum nicht. Schließt das eigene Prüfartefakt dieses Vorlaufs
    aus (sonst würde dessen Schreiben den Fingerprint selbst ändern).

    Nutzt NUL-separierte ``git status -z``-Ausgabe: Pfade mit
    Sonderzeichen (z. B. Umlauten) und Rename-/Copy-Einträge lassen
    sich in der quotierten Textform sonst nicht zuverlässig als
    Dateipfad erkennen.
    """
    head = _git(project_root, "rev-parse", "HEAD").strip()
    status = _git(
        project_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "-z",
    )
    hasher = hashlib.sha256()
    hasher.update(head.encode())
    for code, path, orig_path in _parse_status_z(status):
        paths = (path,) if orig_path is None else (path, orig_path)
        if any(_excluded(candidate) for candidate in paths):
            continue
        hasher.update(code.encode())
        for candidate in paths:
            hasher.update(candidate.encode())
        full = project_root / path
        if full.is_file():
            try:
                hasher.update(full.read_bytes())
            except OSError:
                hasher.update(b"<unlesbar>")
    return hasher.hexdigest()


def _parse_status_z(raw: str) -> list[tuple[str, str, str | None]]:
    """Parst NUL-separierte ``git status --porcelain=v1 -z``-Ausgabe.

    Jeder Eintrag ist ``XY PATH``; ist X oder Y ``R``/``C`` (Rename/
    Copy), folgt ein zweites NUL-terminiertes Feld mit dem
    Ursprungspfad.
    """
    fields = raw.split("\0")
    if fields and fields[-1] == "":
        fields = fields[:-1]
    entries: list[tuple[str, str, str | None]] = []
    index = 0
    while index < len(fields):
        field = fields[index]
        index += 1
        if len(field) < 4:
            continue
        code = field[:2]
        path = field[3:]
        orig_path: str | None = None
        is_rename_or_copy = code[0] in "RC" or code[1] in "RC"
        if is_rename_or_copy and index < len(fields):
            orig_path = fields[index]
            index += 1
        entries.append((code, path, orig_path))
    return entries


def _excluded(path: str) -> bool:
    return any(
        path == excl or path.startswith(excl + "/")
        for excl in _FINGERPRINT_EXCLUDES
    )


def _git(project_root: Path, *args: str) -> str:
    """Git-Aufruf für den Fingerprint: strikt dekodiert, nicht
    verlustbehaftet, ohne Zeilenendenübersetzung.

    Der Fingerprint bindet den Bericht an exakte Pfade und
    Dateiinhalte. ``text=True`` würde nicht nur ``errors="replace"``
    Pfade verfälschen können, sondern per Universal-Newlines auch ein
    rohes ``\\r`` in einem Dateinamen in ``\\n`` umwandeln; zwei
    verschiedene Pfade könnten so auf dieselbe Zeichenkette und damit
    denselben Fingerprint abbilden. Deshalb werden rohe Bytes gelesen
    und ohne Zeilenendenübersetzung strikt dekodiert; nicht dekodier-
    bare Ausgabe gilt als Ausführungsfehler, nicht als stillschweigend
    ersetzter oder umgewandelter Text.
    """
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=project_root,
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise PreflightExecutionError(
            f"git {' '.join(args)} fehlgeschlagen: "
            f"exit={exc.returncode}"
        ) from exc
    except OSError as exc:
        raise PreflightExecutionError(
            f"git nicht ausführbar: {exc}"
        ) from exc
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PreflightExecutionError(
            f"git {' '.join(args)}: Ausgabe nicht als UTF-8 "
            f"dekodierbar: {exc}"
        ) from exc


def _write_artifact(
    project_root: Path, report: PreflightReport
) -> Path:
    directory = project_root / ARTIFACT_DIR
    payload = {
        "source_fingerprint": report.source_fingerprint,
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
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        path = (
            directory / f"{stamp}-{report.source_fingerprint[:12]}.json"
        )
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
    tatsächlichen argv) zeigen. name/argv stammen aus der Konfiguration,
    nicht aus Prozessausgabe, werden aber ebenso bereinigt und begrenzt
    wie bounded_detail: kein voller Log, keine Steuerzeichen/ANSI-Codes
    im Agentenkontext.
    """
    name = _bounded(_clean(item.name), _MAX_SUCCESS_DETAIL_CHARS)
    argv_text = _bounded(_clean(shlex.join(item.argv)), _MAX_ARGV_CHARS)
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
    lines = [
        f"PRUEFBERICHT git={report.source_fingerprint}",
    ]
    lines += [format_command_result(item) for item in report.commands]
    return render_handoff(issue, Step.REVIEW) + "\n".join(lines) + "\n"
