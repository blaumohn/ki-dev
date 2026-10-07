"""Neutrale Datentypen und Vertrag fuer Sitzungstranskripte.

Beide Anbieteradapter liefern denselben Typ; ``validate_transcript``
prueft ihn als Daten im Speicher gegen einen gemeinsamen JSON-Schema-
Vertrag. ``ordinal`` ist die Herkunftsnummer der Quelle (Claude hat
keine und bleibt ``None``), ``position`` die normalisierte Reihenfolge.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from jsonschema import Draft202012Validator

MAX_PROBLEMS = 10


@dataclass(frozen=True)
class TranscriptMessage:
    ordinal: int | float | None
    role: str
    text: str
    source_line: int
    position: int
    timestamp: str | None = None


@dataclass(frozen=True)
class SessionTranscript:
    agent: str
    session_id: str
    source_digest: str
    parser_version: str
    started_at: str | None
    last_activity_at: str | None
    messages: tuple[TranscriptMessage, ...]
    diagnostics: Mapping[str, int]


class TranscriptError(ValueError):
    """Sitzung nicht lesbar oder nicht plausibel.

    ``problems`` nennt nur Pruefcode, Zeile, Feldpfad und Zaehler,
    niemals Gespraechsinhalte oder Rohereignisse.
    """

    def __init__(self, problems: tuple[str, ...]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class TranscriptRequestError(TranscriptError):
    """Anbieter oder Sitzungs-ID ungueltig (vor jedem Dateizugriff)."""

    def __init__(self, problem: str) -> None:
        super().__init__((problem,))


# Zeitzone ist Pflicht, damit Zeitstempel vergleichbar bleiben.
_TIMESTAMP_PATTERN = (
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(\.[0-9]{1,9})?(Z|[+-][0-9]{2}:[0-9]{2})$"
)
_TIMESTAMP_RE = re.compile(_TIMESTAMP_PATTERN)
TIMESTAMP_SCHEMA = {"type": "string", "pattern": _TIMESTAMP_PATTERN}
_OPTIONAL_TIMESTAMP = {"oneOf": [{"type": "null"}, TIMESTAMP_SCHEMA]}
TEXT_SCHEMA = {"type": "string", "pattern": r"\S"}
_COMPONENT = {
    "type": "string",
    "pattern": r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
}

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "agent",
        "session_id",
        "source_digest",
        "parser_version",
        "started_at",
        "last_activity_at",
        "messages",
        "diagnostics",
    ],
    "properties": {
        "agent": {"enum": ["codex", "claude"]},
        "session_id": _COMPONENT,
        "source_digest": {
            "type": "string",
            "pattern": r"^[0-9a-f]{64}$",
        },
        "parser_version": _COMPONENT,
        "started_at": _OPTIONAL_TIMESTAMP,
        "last_activity_at": _OPTIONAL_TIMESTAMP,
        "messages": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "ordinal",
                    "role",
                    "text",
                    "source_line",
                    "position",
                    "timestamp",
                ],
                "properties": {
                    "ordinal": {"type": ["integer", "number", "null"]},
                    "role": {"enum": ["user", "assistant"]},
                    "text": TEXT_SCHEMA,
                    "source_line": {"type": "integer", "minimum": 1},
                    "position": {"type": "integer", "minimum": 1},
                    "timestamp": _OPTIONAL_TIMESTAMP,
                },
            },
        },
        "diagnostics": {
            "type": "object",
            "maxProperties": 40,
            "propertyNames": {
                "pattern": r"^[A-Za-z][A-Za-z0-9_]{0,59}$"
            },
            "additionalProperties": {"type": "integer", "minimum": 0},
        },
    },
}
_VALIDATOR = Draft202012Validator(_SCHEMA)
_FOREIGN = object()


def validate_transcript(transcript: SessionTranscript) -> None:
    """Gemeinsamer Vertrag; auch fuer bereits erzeugte Objekte.

    Das Schema prueft Typen und Felder, benannte Pruefungen die
    Beziehungen zwischen Nachrichten. Diagnosen nennen nur Feldpfad
    und Regel, nie Werte. Falsche Python-Typen (etwa ``messages=None``)
    werden als Vertragsfehler gemeldet, nicht als ``TypeError``.
    """
    if not isinstance(transcript, SessionTranscript):
        raise TranscriptError(("Vertrag: kein SessionTranscript",))
    document = _as_document(transcript)
    problems = [
        schema_problem(error)
        for error in sorted(
            _VALIDATOR.iter_errors(document),
            key=lambda e: [str(p) for p in e.absolute_path],
        )
    ]
    if not problems:
        problems = _relation_problems(transcript)
    if problems:
        omitted = len(problems) - MAX_PROBLEMS
        shown = tuple(problems[:MAX_PROBLEMS])
        more = (
            (f"{omitted} weitere ausgelassen",) if omitted > 0 else ()
        )
        raise TranscriptError(shown + more)


def dialog_advisories(roles: Sequence[str]) -> dict[str, int]:
    """Nichtblockierende Ablaufdiagnosen T1/T2/T4 als Zaehler.

    Wiederholte Rollen, Nachtraege und offene Dialogenden sind gueltig;
    die Zaehler machen sie nur sichtbar.
    """
    users = sum(role == "user" for role in roles)
    assistants = len(roles) - users
    both = users > 0 and assistants > 0
    return {
        "T1_single_role": int(bool(roles) and not both),
        "T2_count_mismatch": int(both and users != assistants),
        "T4_role_breaks": sum(
            role != ("user" if index % 2 == 0 else "assistant")
            for index, role in enumerate(roles)
        ),
    }


def require_started_at(transcript: SessionTranscript) -> datetime:
    """Startdatum fuer datumsbasierte Ablage; fehlt es, ist das ein
    sichtbarer Fehler (kein Export- oder Dateidatum als Ersatz)."""
    if transcript.started_at is None:
        raise TranscriptError(
            (
                "Sitzungsstart nicht belegt (started_at fehlt); "
                "datumsbasierter Export nicht moeglich",
            )
        )
    return parse_timestamp(transcript.started_at)


def parse_timestamp(value: str) -> datetime:
    """ISO-8601-Zeitstempel mit Zone; sonst ``ValueError`` ohne Wert."""
    if not _TIMESTAMP_RE.fullmatch(value):
        raise ValueError("Zeitstempel ohne gueltiges ISO-8601-Format")
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        raise ValueError(
            "Zeitstempel ist kein gueltiges Datum"
        ) from None


def is_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parse_timestamp(value)
    except ValueError:
        return False
    return True


def decode_utf8(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TranscriptError(
            (f"J0 Datei ist kein gueltiges UTF-8 (Byte {exc.start})",)
        ) from None


def line_count(data: bytes) -> int:
    return data.count(b"\n") + (not data.endswith(b"\n"))


def _as_document(transcript: SessionTranscript) -> dict:
    """Schema-Sicht; unerwartete Python-Typen bleiben roh stehen und
    scheitern so an der Schemapruefung statt an der Umwandlung."""
    messages = transcript.messages
    diagnostics = transcript.diagnostics
    return {
        "agent": transcript.agent,
        "session_id": transcript.session_id,
        "source_digest": transcript.source_digest,
        "parser_version": transcript.parser_version,
        "started_at": transcript.started_at,
        "last_activity_at": transcript.last_activity_at,
        "messages": (
            [_message_document(message) for message in messages]
            if isinstance(messages, tuple | list)
            else messages
        ),
        "diagnostics": (
            dict(diagnostics)
            if isinstance(diagnostics, Mapping)
            else diagnostics
        ),
    }


def _message_document(message: object) -> object:
    if not isinstance(message, TranscriptMessage):
        # Kein Objekt im Schemasinn: scheitert an messages[i] (type).
        return _FOREIGN
    return {
        "ordinal": message.ordinal,
        "role": message.role,
        "text": message.text,
        "source_line": message.source_line,
        "position": message.position,
        "timestamp": message.timestamp,
    }


def schema_problem(error) -> str:
    # Nur Pfad und Regel; error.message/instance enthalten Rohwerte.
    path = "".join(
        f"[{part}]" if isinstance(part, int) else f".{part}"
        for part in error.absolute_path
    ).lstrip(".")
    return f"Vertrag: Feld {path or '<root>'} ({error.validator})"


def _relation_problems(transcript: SessionTranscript) -> list[str]:
    messages = transcript.messages
    problems = []
    if [m.position for m in messages] != list(
        range(1, len(messages) + 1)
    ):
        problems.append(
            "Vertrag: messages.position nicht fortlaufend ab 1"
        )
    problems += _ordinal_problems(messages)
    problems += _timestamp_problems(transcript)
    return problems


def _ordinal_problems(
    messages: tuple[TranscriptMessage, ...],
) -> list[str]:
    present = [m.ordinal for m in messages if m.ordinal is not None]
    if present and len(present) != len(messages):
        return ["Vertrag: messages.ordinal nur teilweise belegt"]
    if any(
        isinstance(o, float) and not math.isfinite(o) for o in present
    ):
        return ["Vertrag: messages.ordinal nicht endlich"]
    if len(set(present)) != len(present):
        return ["Vertrag: messages.ordinal doppelt"]
    return []


def _timestamp_problems(transcript: SessionTranscript) -> list[str]:
    stamps = {
        "started_at": transcript.started_at,
        "last_activity_at": transcript.last_activity_at,
    } | {
        f"messages[{index}].timestamp": message.timestamp
        for index, message in enumerate(transcript.messages)
    }
    problems = [
        f"Vertrag: Feld {path} (kein gueltiges Datum)"
        for path, value in stamps.items()
        if value is not None and not is_timestamp(value)
    ]
    if problems:
        return problems
    start, last = transcript.started_at, transcript.last_activity_at
    if (
        start
        and last
        and parse_timestamp(last) < parse_timestamp(start)
    ):
        problems.append(
            "Vertrag: last_activity_at liegt vor started_at"
        )
    return problems
