"""Schemata und bereinigte Validierungsfehler für Claude-Transkripte."""

from jsonschema import Draft202012Validator

from .session_transcript import TranscriptError

_STRING = {"type": "string", "minLength": 1}
_BLOCK = {
    "type": "object",
    "required": ["type"],
    "properties": {"type": _STRING, "text": {"type": "string"}},
    "allOf": [
        {
            "if": {"properties": {"type": {"const": "text"}}},
            "then": {"required": ["text"]},
        }
    ],
}
ENVELOPE = Draft202012Validator(
    {
        "type": "object",
        "required": ["type"],
        "properties": {
            "type": _STRING,
            "uuid": _STRING,
            "parentUuid": {"type": ["string", "null"]},
            "isSidechain": {"type": "boolean"},
            "isMeta": {"type": "boolean"},
            "isApiErrorMessage": {"type": "boolean"},
        },
    }
)
MESSAGE = Draft202012Validator(
    {
        "type": "object",
        "required": [
            "uuid",
            "parentUuid",
            "sessionId",
            "isSidechain",
            "message",
        ],
        "properties": {
            "sessionId": _STRING,
            "timestamp": _STRING,
            "origin": {
                "type": "object",
                "required": ["kind"],
                "properties": {"kind": _STRING},
            },
            "turnOrigin": _STRING,
            "promptSource": _STRING,
            "message": {
                "type": "object",
                "required": ["role", "content"],
                "properties": {
                    "role": {"enum": ["user", "assistant"]},
                    "model": _STRING,
                    "stop_reason": {"type": ["string", "null"]},
                    "content": {
                        "oneOf": [
                            {"type": "string"},
                            {"type": "array", "items": _BLOCK},
                        ]
                    },
                },
            },
        },
    }
)
# Belegte technische Herkunft; ein XML-Tag allein ist kein Nachweis.
TASK_NOTIFICATION = Draft202012Validator(
    {
        "required": ["origin", "turnOrigin", "promptSource"],
        "properties": {
            "origin": {
                "properties": {"kind": {"const": "task-notification"}}
            },
            "turnOrigin": {"const": "task_notification"},
            "promptSource": {"const": "system"},
            "message": {"properties": {"content": {"type": "string"}}},
        },
    }
)

# Zusammenfassung nach einer Kontextverdichtung: Claude schreibt sie als
# user-Zeile mit beiden Kennzeichen und ohne jede Herkunftsangabe. Ein
# Kennzeichen allein oder ein Herkunftsfeld daneben belegt nichts.
COMPACT_SUMMARY = Draft202012Validator(
    {
        "required": ["isCompactSummary", "isVisibleInTranscriptOnly"],
        "properties": {
            "isCompactSummary": {"const": True},
            "isVisibleInTranscriptOnly": {"const": True},
            "message": {"properties": {"content": {"type": "string"}}},
        },
        "not": {
            "anyOf": [
                {"required": [key]}
                for key in ("origin", "turnOrigin", "promptSource")
            ]
        },
    }
)

# Explizites null kennzeichnet laufende oder unterbrochene Antworten.
ASSISTANT_TEXT_PHASES = {
    "end_turn": "final",
    "tool_use": "commentary",
    None: "commentary",
}
ASSISTANT_TEXT = Draft202012Validator(
    {
        "type": "object",
        "required": ["stop_reason"],
        "properties": {
            "stop_reason": {"enum": list(ASSISTANT_TEXT_PHASES)},
        },
    }
)


def validate_record(validator, entry: object, number: int) -> None:
    error = next(validator.iter_errors(entry), None)
    if error is None:
        return
    # Nur Schemapfade; niemals error.message/instance.
    path = (
        ".".join(str(part) for part in error.absolute_path) or "<root>"
    )
    rule = error.validator
    if rule == "required":
        missing = [
            key
            for key in error.validator_value
            if key not in error.instance
        ]
        rule = f"fehlt: {', '.join(missing)}"
    raise line_error(number, f"ungueltiges Feld {path} ({rule})")


def line_error(line: int, problem: str) -> TranscriptError:
    return TranscriptError((f"Zeile {line}: {problem}",))
