"""Lesender Beads-Adapter: bd --readonly show BEAD_ID --json."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ki_dev.handoff import HandoffIssue

BD_TIMEOUT_S = 10


class BeadsReadError(RuntimeError):
    """bd lieferte keinen brauchbaren Bead (Adapterfehler)."""


class InvalidBeadIdError(BeadsReadError):
    """Bead-ID ist leer oder sieht wie eine Option aus."""


def read_issue(bead_id: str, workdir: Path) -> HandoffIssue:
    """Einen Bead lesen und zu normalisierten Rohwerten machen."""
    _check_bead_id(bead_id)
    stdout = _run_bd(
        ["bd", "--readonly", "show", bead_id, "--json"], workdir
    )
    return _normalize(_single_object(stdout, bead_id))


def _check_bead_id(bead_id: str) -> None:
    if not bead_id.strip() or bead_id.startswith("-"):
        raise InvalidBeadIdError(
            "BEAD_ID darf nicht leer sein und nicht mit '-' beginnen"
        )


def _run_bd(argv: list[str], workdir: Path) -> str:
    try:
        completed = subprocess.run(
            argv,
            cwd=workdir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=BD_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError as exc:
        raise BeadsReadError("bd wurde nicht gefunden") from exc
    except subprocess.TimeoutExpired as exc:
        raise BeadsReadError(
            f"bd antwortete nicht innerhalb von {BD_TIMEOUT_S} s"
        ) from exc
    except (OSError, UnicodeDecodeError) as exc:
        raise BeadsReadError(
            f"bd konnte nicht gelesen werden ({type(exc).__name__})"
        ) from exc
    if completed.returncode != 0:
        raise BeadsReadError(_failure_message(completed))
    return completed.stdout


def _failure_message(
    completed: subprocess.CompletedProcess[str],
) -> str:
    # Feste Ursache: bd-Ausgabe könnte Roh-JSON enthalten.
    return f"bd endete mit Exit-Code {completed.returncode}"


def _single_object(stdout: str, bead_id: str) -> dict:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise BeadsReadError("bd lieferte kein gültiges JSON") from exc
    if not (
        isinstance(data, list)
        and len(data) == 1
        and isinstance(data[0], dict)
    ):
        raise BeadsReadError(
            "bd-Antwort ist keine Liste mit genau einem Objekt"
        )
    if data[0].get("id") != bead_id:
        raise BeadsReadError(
            "bd lieferte einen Bead mit abweichender id"
        )
    return data[0]


def _normalize(raw: dict) -> HandoffIssue:
    return HandoffIssue(
        id=raw.get("id"),
        title=raw.get("title"),
        description=raw.get("description"),
        design=raw.get("design"),
        acceptance_criteria=raw.get("acceptance_criteria"),
        source_refs=_source_refs(raw.get("metadata")),
    )


def _source_refs(metadata: object) -> object:
    handoff = (
        metadata.get("handoff") if isinstance(metadata, dict) else None
    )
    return (
        handoff.get("source_refs")
        if isinstance(handoff, dict)
        else None
    )
