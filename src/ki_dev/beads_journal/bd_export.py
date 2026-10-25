"""bd export für das Beads-Journal: Zeilen lesen und prüfen.

export_rows liefert die vollständigen Zeilen (comments liest daraus die
bd-Kommentare), export_issues die Hook-Form für init und index.
"""

from __future__ import annotations

import json
from pathlib import Path

from plumbum import local
from plumbum.commands.processes import (
    CommandNotFound,
    ProcessExecutionError,
    ProcessTimedOut,
)

from ki_dev.beads_journal.contract import PayloadError, check_issue
from ki_dev.beads_journal.journal import JournalError

BD_PROGRAM = "bd"
EXPORT_TIMEOUT = 60
# Nur bd export liefert diese Felder, die Hook-Nutzlast nicht. Ohne sie
# entspricht der Erststand der Hook-Form: das erste Ereignis zeigt keine
# Scheinlöschungen, und Kommentartexte gelangen nicht ins Journal.
EXPORT_ONLY_FIELDS = (
    "comments",
    "comment_count",
    "dependency_count",
    "dependent_count",
)


def export_issues(root: Path) -> list[dict]:
    """bd export in Hook-Form: ohne EXPORT_ONLY_FIELDS."""
    rows = export_rows(root)
    for row in rows:
        for field in EXPORT_ONLY_FIELDS:
            row.pop(field, None)
    return rows


def export_rows(root: Path) -> list[dict]:
    """bd export ohne Memories und Infrastruktur; jede Zeile geprüft."""
    try:
        with local.cwd(root):
            _, stdout, _ = local[BD_PROGRAM][
                "--readonly", "export"
            ].run(retcode=0, timeout=EXPORT_TIMEOUT)
    except CommandNotFound as exc:
        raise JournalError("bd nicht gefunden") from exc
    except ProcessTimedOut as exc:
        raise JournalError(
            f"bd export: über {EXPORT_TIMEOUT} s"
        ) from exc
    except ProcessExecutionError as exc:
        raise JournalError(f"bd export: Exit {exc.retcode}") from exc
    return [
        _export_row(line, number)
        for number, line in enumerate(stdout.splitlines(), start=1)
        if line.strip()
    ]


def _export_row(line: str, number: int) -> dict:
    label = f"bd export Zeile {number}"
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise PayloadError(f"{label}: kein JSON") from exc
    if (
        not isinstance(row, dict)
        or row.pop("_type", "issue") != "issue"
    ):
        raise PayloadError(f"{label}: kein Issue-Datensatz")
    check_issue(row, [label])
    return row
