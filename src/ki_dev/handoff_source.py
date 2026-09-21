"""Lokale Quellenablage fuer normalisierte Sitzungstranskripte."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from ki_dev.executors.session_transcript import SessionTranscript

SOURCE_ROOT = Path(".local/handoff")
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


def source_path(transcript: SessionTranscript) -> Path:
    """Relativer Ablagepfad; Wiederholung ergibt denselben Pfad."""
    return (
        SOURCE_ROOT
        / _safe(transcript.agent)
        / _safe(transcript.session_id)
        / (
            f"{_safe(transcript.source_digest)}-"
            f"{_safe(transcript.parser_version)}.jsonl"
        )
    )


def serialize_messages(transcript: SessionTranscript) -> bytes:
    """Genau eine Nachricht je Zeile, deterministisch."""
    lines = (
        json.dumps(
            {
                "ordinal": message.ordinal,
                "role": message.role,
                "text": message.text,
                "source_line": message.source_line,
            },
            ensure_ascii=False,
            allow_nan=False,
        )
        for message in transcript.messages
    )
    return "".join(f"{line}\n" for line in lines).encode("utf-8")


def store_source(transcript: SessionTranscript, workdir: Path) -> Path:
    """Artefakt atomar ablegen; identisches wiederverwenden.

    Rueckgabe ist der relative Pfad. Abweichender Inhalt am selben
    Schluessel ist ein Fehler, nie ein stilles Ueberschreiben.
    """
    relative = source_path(transcript)
    target = workdir / relative
    content = serialize_messages(transcript)
    try:
        if target.exists():
            _require_identical(target, content)
        else:
            _publish_atomically(target, content)
    except OSError as exc:
        raise HandoffSourceError(
            f"Quellen-Datei nicht ablegbar ({type(exc).__name__})"
        ) from None
    return relative


def _require_identical(target: Path, content: bytes) -> None:
    if target.read_bytes() != content:
        raise HandoffSourceError(
            "Quellen-Datei existiert mit abweichendem Inhalt: "
            f"{target.name}"
        )


def _publish_atomically(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    finally:
        Path(tmp_name).unlink(missing_ok=True)


def _safe(part: str) -> str:
    if not _COMPONENT.fullmatch(part):
        raise HandoffSourceError("unsicherer Quellenschluessel")
    return part
