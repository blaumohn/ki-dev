"""Schreibender Beads-Adapter fuer Quellen-Beads (bd ueber Plumbum).

Nur Argumentvektoren, feste Frist, keine Shell und keine direkten
DB-/Exportzugriffe. Fehlertexte enthalten nie bd-Ausgabe.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from plumbum import CommandNotFound, local
from plumbum.commands.processes import ProcessTimedOut

BD_PROGRAM = "bd"
BD_TIMEOUT_S = 10
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.I)


class BeadsSourceError(RuntimeError):
    """Quellen-Bead nicht auffindbar, nicht anlegbar oder mehrdeutig."""


@dataclass(frozen=True)
class SourceBead:
    """Inhalt eines neuen Quellen-Beads (ohne Gespraechsinhalte)."""

    key: str
    title: str
    description: str
    source_ref: str


def ensure_source_bead(source: SourceBead, workdir: Path) -> str:
    """ID des einen Quellen-Beads; legt ihn bei Bedarf an.

    Mehrere Treffer brechen ab. Nach der Anlage wird der Bead ueber
    denselben Schluessel bestaetigt.
    """
    found = find_source_bead(source.key, workdir)
    if found is not None:
        return found
    _run_bd(_create_argv(source), workdir)
    created = find_source_bead(source.key, workdir)
    if created is None:
        raise BeadsSourceError(
            "Quellen-Bead nach der Anlage nicht bestaetigt"
        )
    return created


def find_source_bead(key: str, workdir: Path) -> str | None:
    """bd filtert nur Metadaten-Oberschluessel; der Schluessel wird
    danach exakt verglichen. ``--all`` und ``-n 0`` sind noetig, damit
    auch geschlossene und viele Beads gesehen werden."""
    stdout = _run_bd(
        [
            "list",
            "--all",
            "--has-metadata-key",
            "handoff",
            "--json",
            "-n",
            "0",
        ],
        workdir,
    )
    ids = [
        row.get("id")
        for row in _rows(stdout)
        if _source_key_of(row) == key
    ]
    if not all(isinstance(bead_id, str) and bead_id for bead_id in ids):
        raise BeadsSourceError("Quellen-Bead ohne gueltige id")
    if len(ids) > 1:
        raise BeadsSourceError(
            f"{len(ids)} Quellen-Beads zum selben Schluessel"
        )
    return ids[0] if ids else None


def short_session_reference(session_id: str, workdir: Path) -> str:
    """Kuerzester eindeutiger UUID-Suffix fuer lesbare Quellenangaben.

    Die vollstaendige ID bleibt im source_key und im Snapshot-Pfad.
    """
    if _UUID.fullmatch(session_id) is None:
        raise BeadsSourceError("ungueltige Sitzungs-ID")
    stdout = _run_bd(
        [
            "list",
            "--all",
            "--has-metadata-key",
            "handoff",
            "--json",
            "-n",
            "0",
        ],
        workdir,
    )
    others = set()
    for row in _rows(stdout):
        key = _source_key_of(row)
        if not isinstance(key, str):
            continue
        parts = key.split(":", 2)
        if len(parts) >= 2 and _UUID.fullmatch(parts[1]):
            others.add(parts[1].replace("-", "").lower())
    compact = session_id.replace("-", "").lower()
    for length in range(5, len(compact) + 1):
        suffix = compact[-length:]
        if all(
            other == compact or not other.endswith(suffix)
            for other in others
        ):
            return f"…{suffix}"
    raise BeadsSourceError("Sitzungs-ID nicht eindeutig")


def _create_argv(source: SourceBead) -> list[str]:
    metadata = {
        "handoff": {
            "source_key": source.key,
            "source_refs": [source.source_ref],
        }
    }
    return [
        "create",
        source.title,
        "--type",
        "task",
        "--description",
        source.description,
        "--metadata",
        json.dumps(metadata, ensure_ascii=False),
        "--silent",
    ]


def _rows(stdout: str) -> list[dict]:
    try:
        data = json.loads(stdout)
    except ValueError:
        raise BeadsSourceError(
            "bd lieferte kein gueltiges JSON"
        ) from None
    if not isinstance(data, list) or not all(
        isinstance(row, dict) for row in data
    ):
        raise BeadsSourceError("bd-Antwort ist keine Objektliste")
    return data


def _source_key_of(row: dict) -> object:
    metadata = row.get("metadata")
    handoff = (
        metadata.get("handoff") if isinstance(metadata, dict) else None
    )
    return (
        handoff.get("source_key") if isinstance(handoff, dict) else None
    )


def _run_bd(args: list[str], workdir: Path) -> str:
    try:
        command = local[BD_PROGRAM][tuple(args)]
    except CommandNotFound:
        raise BeadsSourceError("bd wurde nicht gefunden") from None
    try:
        code, stdout, _stderr = command.run(
            retcode=None, timeout=BD_TIMEOUT_S, cwd=workdir
        )
    except ProcessTimedOut:
        raise BeadsSourceError(
            f"bd antwortete nicht innerhalb von {BD_TIMEOUT_S} s"
        ) from None
    except FileNotFoundError:
        raise BeadsSourceError("bd wurde nicht gefunden") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise BeadsSourceError(
            f"bd nicht ausfuehrbar ({type(exc).__name__})"
        ) from None
    if code != 0:
        raise BeadsSourceError(f"bd endete mit Exit-Code {code}")
    return stdout
