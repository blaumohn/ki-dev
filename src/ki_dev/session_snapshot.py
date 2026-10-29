"""Datierte JSONL-Snapshots: Metadatenkopf, dann Nachrichten.

Standalone-Export und ``step map`` teilen Serializer und Speicher.
Identität: (agent, session_id, source_digest, parser_version).
"""

from __future__ import annotations

import glob
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

from jsonschema import Draft202012Validator

from ki_dev.adapter.executors.session_transcript import (
    TEXT_SCHEMA,
    TIMESTAMP_SCHEMA,
    SessionTranscript,
    TranscriptError,
    TranscriptMessage,
    require_started_at,
    schema_problem,
    validate_transcript,
)

SNAPSHOT_DIR = Path(".local/var/transcripts")
FORMAT_VERSION = 1
TITLE_MAX_CHARS = 120
SLUG_MAX_CHARS = 40
_SID_CHARS = 8
_SUFFIX_LENGTHS = (8, 12, 16, 24, 32, 64)
_MESSAGE_FIELDS = (
    "position",
    "ordinal",
    "role",
    "text",
    "source_line",
    "timestamp",
)
_TRANSLITERATION = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
)

# Altformat der ersten handoff-map-Ablage: nur Nachrichtenzeilen, die
# Identitaet steht im Pfad <agent>/<session_id>/<digest>-<parser>.jsonl.
LEGACY_FORMAT = "handoff-v0"
_LEGACY_NAME = re.compile(r"(?P<digest>[0-9a-f]{64})-(?P<parser>.+)")

_TITLE_SCHEMA = TEXT_SCHEMA | {"maxLength": TITLE_MAX_CHARS}
_HEADER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "type",
        "version",
        "agent",
        "session_id",
        "started_at",
        "last_activity_at",
        "title",
        "source_digest",
        "parser_version",
        "diagnostics",
    ],
    # Uebrige Felder prueft der gemeinsame Transkriptvertrag.
    "properties": {
        "type": {"const": "transcript_meta"},
        "version": {"const": FORMAT_VERSION},
        "agent": {},
        "session_id": {},
        "started_at": TIMESTAMP_SCHEMA,
        "last_activity_at": {},
        "title": {"anyOf": [_TITLE_SCHEMA, {"type": "null"}]},
        "source_digest": {},
        "parser_version": {},
        "diagnostics": {},
    },
}
_MESSAGE_LINE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["type", *_MESSAGE_FIELDS],
    "properties": {"type": {"const": "message"}}
    | {field: {} for field in _MESSAGE_FIELDS},
}
_SNAPSHOT_SCHEMA = {
    "type": "array",
    "minItems": 2,
    "prefixItems": [_HEADER_SCHEMA],
    "items": _MESSAGE_LINE_SCHEMA,
}
_VALIDATOR = Draft202012Validator(_SNAPSHOT_SCHEMA)
_TITLE_VALIDATOR = Draft202012Validator(_TITLE_SCHEMA)


class SnapshotError(RuntimeError):
    """Snapshot nicht ablegbar, nicht lesbar oder widerspruechlich.

    Meldungen nennen Datei, Zeile, Feldpfad und Regel, nie Inhalte.
    """


class SnapshotTitleError(SnapshotError):
    """Angegebener Titel ist ungültig oder ergibt keinen Dateinamen."""


@dataclass(frozen=True)
class Snapshot:
    """Gelesener Snapshot mit optionalem Titel."""

    format: str
    title: str | None
    transcript: SessionTranscript


def store_snapshot(
    transcript: SessionTranscript, title: str | None, directory: Path
) -> Path:
    """Atomar ablegen; identische Stände wiederverwenden.
    Neue Stände erhalten ein bei Kollision verlängertes Digest-Suffix.
    """
    content = serialize_snapshot(transcript, title)
    base = snapshot_stem(transcript, title)
    existing = _same_identity(transcript, base, directory)
    if existing is not None:
        return existing
    for stem in _candidate_stems(base, transcript.source_digest):
        target = directory / f"{stem}.jsonl"
        if not target.exists() and _publish(target, content):
            return target
    raise SnapshotError(f"kein freier Snapshot-Name fuer {base}.jsonl")


def serialize_snapshot(
    transcript: SessionTranscript, title: str | None
) -> bytes:
    """Geprüften Kopf und Nachrichten deterministisch serialisieren."""
    if title is not None:
        validate_title(title)
    try:
        validate_transcript(transcript)
        require_started_at(transcript)
    except TranscriptError as exc:
        raise SnapshotError(
            "Transkript verletzt den Vertrag: "
            + "; ".join(exc.problems)
        ) from None
    lines = [_header(transcript, title)] + [
        {"type": "message"} | _message_fields(message)
        for message in transcript.messages
    ]
    _check_document(lines, "Snapshot")
    return "".join(
        json.dumps(line, ensure_ascii=False, allow_nan=False) + "\n"
        for line in lines
    ).encode("utf-8")


def snapshot_stem(
    transcript: SessionTranscript, title: str | None
) -> str:
    """UTC-Sitzungsbeginn, optionaler Titelslug/Anbieter und Kurz-ID."""
    started = require_started_at(transcript).astimezone(UTC)
    if not 2000 <= started.year <= 2099:
        raise SnapshotError(
            "Sitzungsbeginn ausserhalb 2000-2099; "
            "YY-Name nicht eindeutig"
        )
    sid8 = transcript.session_id[:_SID_CHARS]
    label = title_slug(title) if title is not None else transcript.agent
    return f"{started:%y%m%dT%H}_{label}_{sid8}"


def validate_title(title: object) -> None:
    if not isinstance(title, str) or any(
        True for _ in _TITLE_VALIDATOR.iter_errors(title)
    ):
        raise SnapshotTitleError(
            "--title muss nichtleerer Text bis "
            f"{TITLE_MAX_CHARS} Zeichen sein"
        )
    title_slug(title)


def title_slug(title: str) -> str:
    """Sicherer, deterministischer Dateislug; nie aus Prompttext."""
    folded = unicodedata.normalize(
        "NFKD", title.lower().translate(_TRANSLITERATION)
    )
    ascii_text = folded.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text).strip("-")
    slug = slug[:SLUG_MAX_CHARS].rstrip("-")
    if not slug:
        raise SnapshotTitleError(
            "--title ergibt keinen Dateinamen; Buchstaben oder Ziffern "
            "verwenden"
        )
    return slug


def read_snapshot(path: Path) -> Snapshot:
    """Version 1 und bekanntes Altformat prüfen; andere ablehnen."""
    lines = _parse_lines(path)
    first = lines[0] if lines else None
    if isinstance(first, dict) and "type" in first:
        return _snapshot_v1(lines, path)
    if lines and all(
        isinstance(line, dict) and set(line) == set(_MESSAGE_FIELDS)
        for line in lines
    ):
        return _snapshot_legacy(lines, path)
    keys = sorted(first) if isinstance(first, dict) else []
    raise SnapshotError(
        f"{path.name}: unbekanntes Snapshot-Format "
        f"(Schluessel Zeile 1: {', '.join(keys) or '-'})"
    )


def _header(transcript: SessionTranscript, title: str | None) -> dict:
    return {
        "type": "transcript_meta",
        "version": FORMAT_VERSION,
        "agent": transcript.agent,
        "session_id": transcript.session_id,
        "started_at": transcript.started_at,
        "last_activity_at": transcript.last_activity_at,
        "title": title,
        "source_digest": transcript.source_digest,
        "parser_version": transcript.parser_version,
        "diagnostics": dict(transcript.diagnostics),
    }


def _message_fields(message: TranscriptMessage) -> dict:
    return {field: getattr(message, field) for field in _MESSAGE_FIELDS}


def _check_document(lines: list, label: str) -> None:
    errors = sorted(
        _VALIDATOR.iter_errors(lines),
        key=lambda e: [str(p) for p in e.absolute_path],
    )
    if errors:
        # Feldpfad [0] ist Zeile 1 usw.; Werte erscheinen nie.
        raise SnapshotError(
            f"{label}: "
            + "; ".join(schema_problem(e) for e in errors[:5])
        )


def _same_identity(
    transcript: SessionTranscript, base: str, directory: Path
) -> Path | None:
    """Vorhandener Snapshot derselben Identitaet, unabhaengig vom Titel.

    Gleiche Identitaet mit abweichendem Inhalt ist ein Fehler.
    """
    # base beginnt mit YYMMDDTHH; die ID kann selbst "_" enthalten.
    sid8 = transcript.session_id[:_SID_CHARS]
    pattern = f"{glob.escape(base[:9])}_*_{glob.escape(sid8)}*.jsonl"
    for path in sorted(directory.glob(pattern)):
        stored = read_snapshot(path).transcript
        if _identity(stored) != _identity(transcript):
            continue
        if stored != transcript:
            raise SnapshotError(
                f"{path.name}: abweichender Inhalt bei identischem "
                "Schluessel (agent, session_id, source_digest, "
                "parser_version)"
            )
        return path
    return None


def _identity(transcript: SessionTranscript) -> tuple[str, ...]:
    return (
        transcript.agent,
        transcript.session_id,
        transcript.source_digest,
        transcript.parser_version,
    )


def _candidate_stems(base: str, digest: str) -> list[str]:
    return [base] + [f"{base}-{digest[:n]}" for n in _SUFFIX_LENGTHS]


def _publish(target: Path, content: bytes) -> bool:
    """Atomar und ohne Ueberschreiben; ``False`` nur, wenn der Name
    zwischenzeitlich belegt wurde. Fehler hinterlassen keine Datei."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=target.parent, prefix=".tmp-"
        )
    except OSError as exc:
        raise SnapshotError(
            f"Snapshot nicht ablegbar ({type(exc).__name__})"
        ) from None
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(tmp_name, target)
    except FileExistsError:
        return False
    except OSError as exc:
        raise SnapshotError(
            f"Snapshot nicht ablegbar ({type(exc).__name__})"
        ) from None
    finally:
        Path(tmp_name).unlink(missing_ok=True)
    return True


def _parse_lines(path: Path) -> list:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise SnapshotError(
            f"{path.name}: nicht lesbar ({type(exc).__name__})"
        ) from None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise SnapshotError(
            f"{path.name}: kein gueltiges UTF-8"
        ) from None
    lines = []
    for number, raw in enumerate(text.splitlines(), start=1):
        try:
            lines.append(json.loads(raw))
        except ValueError:
            raise SnapshotError(
                f"{path.name}: Zeile {number} ist kein JSON"
            ) from None
    if not lines:
        raise SnapshotError(f"{path.name}: leer")
    return lines


def _snapshot_v1(lines: list, path: Path) -> Snapshot:
    _check_document(lines, path.name)
    header = lines[0]
    transcript = SessionTranscript(
        agent=header["agent"],
        session_id=header["session_id"],
        source_digest=header["source_digest"],
        parser_version=header["parser_version"],
        started_at=header["started_at"],
        last_activity_at=header["last_activity_at"],
        messages=_messages(lines[1:]),
        diagnostics=header["diagnostics"],
    )
    _validate(transcript, path)
    return Snapshot(f"v{FORMAT_VERSION}", header["title"], transcript)


def _snapshot_legacy(lines: list, path: Path) -> Snapshot:
    match = _LEGACY_NAME.fullmatch(path.stem)
    if match is None or len(path.parts) < 3:
        raise SnapshotError(
            f"{path.name}: Altformat {LEGACY_FORMAT} nur unter "
            "<agent>/<session_id>/<digest>-<parser>.jsonl lesbar"
        )
    transcript = SessionTranscript(
        agent=path.parent.parent.name,
        session_id=path.parent.name,
        source_digest=match["digest"],
        parser_version=match["parser"],
        started_at=None,
        last_activity_at=None,
        messages=_messages(lines),
        diagnostics={},
    )
    _validate(transcript, path)
    return Snapshot(LEGACY_FORMAT, None, transcript)


def _messages(lines: list) -> tuple[TranscriptMessage, ...]:
    return tuple(
        TranscriptMessage(**{f: line[f] for f in _MESSAGE_FIELDS})
        for line in lines
    )


def _validate(transcript: SessionTranscript, path: Path) -> None:
    try:
        validate_transcript(transcript)
    except TranscriptError as exc:
        raise SnapshotError(
            f"{path.name}: " + "; ".join(exc.problems)
        ) from None
