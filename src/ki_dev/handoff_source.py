"""Quellenablage fuer step map: Schluessel, Snapshot und Altpfad."""

from __future__ import annotations

import re
from pathlib import Path

from ki_dev.executors.session_transcript import SessionTranscript
from ki_dev.session_snapshot import (
    SNAPSHOT_DIR,
    SnapshotError,
    store_snapshot,
)

LEGACY_SOURCE_ROOT = Path(".local/handoff")
_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")


class HandoffSourceError(RuntimeError):
    """Quellen-Artefakt nicht ablegbar oder widerspruechlich."""


def source_key(transcript: SessionTranscript) -> str:
    """(agent, session_id, source_digest, parser_version) als Text."""
    return ":".join(
        _safe(part)
        for part in (
            transcript.agent,
            transcript.session_id,
            transcript.source_digest,
            transcript.parser_version,
        )
    )


def legacy_source_path(transcript: SessionTranscript) -> Path:
    """Pfad der frueheren Ablage (Altformat ``handoff-v0``).

    Bestehende Quellen-Beads verweisen weiter darauf; neu geschrieben
    wird dort nichts mehr.
    """
    return (
        LEGACY_SOURCE_ROOT
        / _safe(transcript.agent)
        / _safe(transcript.session_id)
        / (
            f"{_safe(transcript.source_digest)}-"
            f"{_safe(transcript.parser_version)}.jsonl"
        )
    )


def store_source(
    transcript: SessionTranscript, title: str, workdir: Path
) -> Path:
    """Snapshot im gemeinsamen Speicher ablegen; relativer Pfad.

    Identischer Stand wird wiederverwendet; ein Transkript ausserhalb
    des gemeinsamen Vertrags wird nie abgelegt.
    """
    try:
        path = store_snapshot(transcript, title, workdir / SNAPSHOT_DIR)
    except SnapshotError as exc:
        raise HandoffSourceError(str(exc)) from None
    return path.relative_to(workdir)


def accepted_refs(
    transcript: SessionTranscript, stored: Path, workdir: Path
) -> tuple[str, ...]:
    """Verweise, die ein Quellen-Bead fuer diesen Stand tragen darf.

    Neben dem neuen Snapshot gilt eine vorhandene Altablage desselben
    Schluessels, damit fruehere Quellen-Beads weiter verwendbar sind.
    """
    legacy = legacy_source_path(transcript)
    refs = [stored.as_posix()]
    if (workdir / legacy).is_file():
        refs.append(legacy.as_posix())
    return tuple(refs)


def _safe(part: str) -> str:
    if not _COMPONENT.fullmatch(part):
        raise HandoffSourceError("unsicherer Quellenschluessel")
    return part
