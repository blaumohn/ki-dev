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

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")

# Eigenes Prüfartefakt dieses Vorlaufs: vom Fingerprint ausgeschlossen,
# sonst würde das Schreiben des Berichts den geprüften Stand selbst
# verändern.
_FINGERPRINT_EXCLUDES = (str(ARTIFACT_DIR),)

Status = Literal["pass", "fail", "omitted"]


class PreflightConfigError(ValueError):
    """Aufruf/Bead/Konfiguration ungültig; keine Schreibwirkung."""


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
                "tool.ki-dev.handoff.preflight fehlt in "
                f"{path}"
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


def _parse_commands(
    raw: object, field: str
) -> tuple[CommandSpec, ...]:
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
        return _finish(project_root, results, valid=False)

    fingerprint_before_checks = _fingerprint(project_root)
    checks_ok = True
    for spec in config.checks:
        result = _run_command(project_root, spec)
        results.append(result)
        if result.status != "pass":
            checks_ok = False
    fingerprint_after_checks = _fingerprint(project_root)
    stable = fingerprint_before_checks == fingerprint_after_checks
    return _finish(
        project_root,
        results,
        valid=checks_ok and stable,
        fingerprint=fingerprint_before_checks,
    )


def _finish(
    project_root: Path,
    results: list[CommandResult],
    *,
    valid: bool,
    fingerprint: str | None = None,
) -> PreflightReport:
    report = PreflightReport(
        fingerprint if fingerprint is not None else _fingerprint(
            project_root
        ),
        tuple(results),
        valid,
    )
    _write_artifact(project_root, report)
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
            timeout=spec.timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CommandResult(
            spec.name,
            "fail",
            None,
            f"Timeout nach {spec.timeout_s:g} s",
            omitted=False,
        )
    except OSError as exc:
        return CommandResult(
            spec.name,
            "fail",
            None,
            _bounded(f"Startfehler: {exc}", _MAX_FAILURE_DETAIL_CHARS),
            omitted=False,
        )
    passed = completed.returncode == 0
    return CommandResult(
        spec.name,
        "pass" if passed else "fail",
        completed.returncode,
        _exit_detail(
            completed.returncode, completed.stdout + completed.stderr
        ),
        omitted=False,
    )


def _exit_detail(returncode: int, output: str) -> str:
    text = _CONTROL_CHARS.sub("", _ANSI_ESCAPE.sub("", output)).strip()
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
    aus (sonst würde dessen Schreiben den Fingerprint selbst ändern)."""
    head = _git(project_root, "rev-parse", "HEAD").strip()
    status = _git(
        project_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    hasher = hashlib.sha256()
    hasher.update(head.encode())
    for line in status.splitlines():
        path = line[3:]
        if _excluded(path):
            continue
        hasher.update(line.encode())
        full = project_root / path
        if full.is_file():
            try:
                hasher.update(full.read_bytes())
            except OSError:
                hasher.update(b"<unlesbar>")
    return hasher.hexdigest()


def _excluded(path: str) -> bool:
    return any(
        path == excl or path.startswith(excl + "/")
        for excl in _FINGERPRINT_EXCLUDES
    )


def _git(project_root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout


def _write_artifact(
    project_root: Path, report: PreflightReport
) -> Path:
    directory = project_root / ARTIFACT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = directory / f"{stamp}-{report.source_fingerprint[:12]}.json"
    payload = {
        "source_fingerprint": report.source_fingerprint,
        "valid": report.valid,
        "commands": [
            {
                "name": item.name,
                "status": item.status,
                "exit_code": item.exit_code,
                "detail": item.bounded_detail,
                "omitted": item.omitted,
            }
            for item in report.commands
        ],
    }
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    )
    return path


def render_review_handoff(
    issue: HandoffIssue, report: PreflightReport
) -> str:
    """Reines Rendering: hängt den kompakten Vorlaufbericht an die
    Review-Übergabe (``handoff.render_handoff``) an."""
    lines = [
        f"PRUEFBERICHT git={report.source_fingerprint}",
    ]
    lines += [
        f"- {item.name}: {item.status.upper()} "
        f"{item.bounded_detail}".rstrip()
        for item in report.commands
    ]
    return render_handoff(issue, Step.REVIEW) + "\n".join(lines) + "\n"
