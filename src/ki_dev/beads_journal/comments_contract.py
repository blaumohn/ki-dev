"""Vertrag des Kommentar-Journals: comments/<ID>.json und bd-Kommentare.

Felder id, author, created_at und text wie in bd export, dazu der
Einbau-Zustand state. Schlüssel zum Abgleich ist id. Meldungen nennen
Datei und Feldpfad, keine Werte; Verstöße an Dateien tragen den
Rücksetzhinweis, denn sie entstehen nur durch Handbearbeitung.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from ki_dev.beads_journal.contract import (
    ID_PATTERN,
    PayloadError,
    check_schema,
)

COMMENTS = "comments"
LABEL = "comments:open"
OPEN = "open"
INCORPORATED = "incorporated"
COMMAND = ".venv/bin/python -m ki_dev.beads_journal comments"
FIELDS = ("id", "author", "created_at", "text")
_STRING = {"type": "string"}
_ENTRY = {
    "id": {"type": "string", "pattern": r"\S"},
    "author": _STRING,
    "created_at": _STRING,
    "text": _STRING,
}
_BD_COMMENTS = Draft202012Validator(
    {
        "type": "array",
        "items": {
            "type": "object",
            "properties": _ENTRY,
            "required": list(FIELDS),
        },
    }
)
_RECORD = Draft202012Validator(
    {
        "type": "object",
        "properties": {
            "issue_id": {"type": "string", "pattern": ID_PATTERN},
            "comments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        **_ENTRY,
                        "state": {"enum": [OPEN, INCORPORATED]},
                    },
                    "required": [*FIELDS, "state"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["issue_id", "comments"],
        "additionalProperties": False,
    }
)


def bd_comments(rows: list[dict]) -> dict[str, list[dict]]:
    """Kommentare je Vorgang aus bd export; nur Vorgänge mit welchen."""
    found = {}
    for row in rows:
        entries = row.get("comments") or []
        check_schema(
            _BD_COMMENTS, entries, [f"bd export {row['id']}.comments"]
        )
        if entries:
            found[row["id"]] = entries
    return found


def load(journal: Path, path: Path) -> dict:
    """Liest comments/<ID>.json; Vertragsverstoß mit Rücksetzhinweis."""
    name = f"{COMMENTS}/{path.name}"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        check_schema(_RECORD, record, [])
        if record["issue_id"] != path.stem:
            raise PayloadError("issue_id: passt nicht zum Dateinamen")
        ids = [entry["id"] for entry in record["comments"]]
        if len(set(ids)) != len(ids):
            raise PayloadError("comments: doppelte id")
    except (OSError, ValueError) as exc:
        reason = (
            exc
            if isinstance(exc, PayloadError)
            else (f"nicht lesbar ({type(exc).__name__})")
        )
        raise PayloadError(
            f"{name}: {reason}. Nicht von Hand bearbeiten. "
            f"Zurücksetzen: git -C {journal} checkout -- {name}, dann "
            f"{COMMAND} mark-incorporated {path.stem}"
        ) from None
    return record


def open_count(record: dict) -> int:
    return sum(entry["state"] == OPEN for entry in record["comments"])


def labelled(rows: list[dict]) -> set[str]:
    return {
        row["id"] for row in rows if LABEL in (row.get("labels") or [])
    }


def comment_file(journal: Path, issue_id: str) -> Path:
    return journal / COMMENTS / f"{issue_id}.json"
