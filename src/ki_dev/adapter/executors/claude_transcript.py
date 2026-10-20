"""Claude-Transkriptadapter: Dialog aus einer Sitzungs-JSONL lesen.

Fachliches Vorbild: ``mdman-ai-session/adapters/claude_transcript.py``
und ``docs/transkript-pruefungen.md``. Uebernommen werden menschliche
Eingaben und ``end_turn``-Textbloecke. Technische Aufgabenmeldungen
werden nur bei belegter Herkunft (``origin.kind``, ``turnOrigin``,
``promptSource`` und String-Inhalt) ausgelassen und gezaehlt,
Slash-Befehlszeilen nur ohne jede Herkunftsangabe; ein XML-Tag allein
belegt nichts, menschliche Zitate bleiben. Zeitstempel sind optional;
``sessionId`` muss der angeforderten Sitzung entsprechen. Wiederholte
Rollen und offene Eingaben
sind gueltig und werden gezaehlt. Unbekannte Herkunft, ungueltiges JSON
und leere Transkripte sind Fehler. Claude kennt keine Quellordinals;
``ordinal`` bleibt ``None``. Keine Rekonstruktion von Resume-/Fork-
Zweigen. Diagnosen nennen nur Zeile, Feldpfad, Regel, bekannte
Kennzeichen und Zaehler -- nie Gespraechsinhalte.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

from .claude_sessions import (
    find_claude_sessions,
    resolve_claude_sessions_dir,
    validate_claude_session_id,
)
from .session_transcript import (
    SessionTranscript,
    TranscriptError,
    TranscriptMessage,
    decode_utf8,
    dialog_advisories,
    is_timestamp,
    line_count,
    parse_timestamp,
    validate_transcript,
)

AGENT = "claude"
PARSER_VERSION = "claude-dialog-1"

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
_ENVELOPE = Draft202012Validator(
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
_MESSAGE = Draft202012Validator(
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
_TASK_NOTIFICATION = Draft202012Validator(
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
_COMPACT_SUMMARY = Draft202012Validator(
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

# Slash-Befehle und ihre Ausgaben stehen als user-Zeilen im Transkript,
# sind aber keine Eingabe an den Agenten.
_LOCAL_COMMAND_TAGS = (
    "command-name",
    "command-message",
    "command-args",
    "local-command-stdout",
    "local-command-stderr",
    "local-command-caveat",
)
_LOCAL_COMMAND_PREFIXES = tuple(
    f"<{tag}>" for tag in _LOCAL_COMMAND_TAGS
)

# Nur diese bekannten Kennzeichen erscheinen woertlich in Diagnosen;
# jeder andere Wert nur als Typ, damit keine Inhalte durchrutschen.
_KNOWN_MARKERS = frozenset(
    {
        "human",
        "task-notification",
        "task_notification",
        "typed",
        "queued",
        "system",
        "sdk",
        "external",
        "end_turn",
        "tool_use",
        "max_tokens",
        "stop_sequence",
        "pause_turn",
        "refusal",
        "text",
        "tool_result",
        "thinking",
        "redacted_thinking",
        "image",
        "document",
    }
)
_KNOWN_TAGS = frozenset(
    {"task-notification", "system-reminder", *_LOCAL_COMMAND_TAGS}
)
_MISSING = object()


def read_claude_session(session_id: str) -> SessionTranscript:
    """Ein-/Ausgabegrenze: Umgebung und Datei nur hier gelesen.

    Erwartete Konfigurations- und Dateifehler werden zu bereinigten
    ``TranscriptError``; Ausnahmetexte des Betriebssystems (Pfade)
    gelangen nicht in die Meldung.
    """
    validate_claude_session_id(session_id)
    try:
        root = resolve_claude_sessions_dir(os.environ, Path.home())
    except ValueError as exc:
        raise TranscriptError(
            (f"Claude-Sitzungsordner nicht bestimmbar: {exc}",)
        ) from None
    except RuntimeError:
        raise TranscriptError(
            (
                "Claude-Sitzungsordner nicht bestimmbar: "
                "Home-Verzeichnis unbekannt",
            )
        ) from None
    try:
        data = _single_session(root, session_id).read_bytes()
    except OSError as exc:
        raise TranscriptError(
            (f"Claude-Sitzung nicht lesbar ({type(exc).__name__})",)
        ) from None
    return transcript_from_bytes(session_id, data)


def transcript_from_bytes(
    session_id: str, data: bytes
) -> SessionTranscript:
    """Reine Extraktion aus genau den Bytes, ueber die der Hash geht."""
    digest = hashlib.sha256(data).hexdigest()
    lines = decode_utf8(data).split("\n")
    stats: Counter[str] = Counter()
    rows, stamps = _extract(
        lines, data.endswith(b"\n"), session_id, stats
    )
    messages = tuple(
        TranscriptMessage(
            ordinal=None,
            role=role,
            text=text,
            source_line=line,
            position=position,
            timestamp=stamp,
        )
        for position, (line, role, text, stamp) in enumerate(rows, 1)
    )
    transcript = SessionTranscript(
        agent=AGENT,
        session_id=session_id,
        source_digest=digest,
        parser_version=PARSER_VERSION,
        started_at=min(stamps, key=parse_timestamp, default=None),
        last_activity_at=max(stamps, key=parse_timestamp, default=None),
        messages=messages,
        diagnostics={
            "lines": line_count(data),
            "user_messages": sum(m.role == "user" for m in messages),
            "assistant_messages": sum(
                m.role == "assistant" for m in messages
            ),
            **dialog_advisories([m.role for m in messages]),
            **stats,
        },
    )
    validate_transcript(transcript)
    return transcript


def _single_session(root: Path, session_id: str) -> Path:
    if not root.is_dir():
        raise TranscriptError(
            ("Claude-Sitzungsordner existiert nicht",)
        )
    found = find_claude_sessions(root, session_id)
    if not found:
        raise TranscriptError(("Claude-Sitzung nicht gefunden",))
    if len(found) > 1:
        raise TranscriptError(
            (f"Claude-Sitzung mehrdeutig ({len(found)} Treffer)",)
        )
    return found[0]


def _fail(line: int, problem: str) -> TranscriptError:
    return TranscriptError((f"Zeile {line}: {problem}",))


def _extract(
    lines: list[str],
    ends_with_newline: bool,
    session_id: str,
    stats: Counter[str],
) -> tuple[list[tuple[int, str, str, str | None]], list[str]]:
    """Dialogzeilen und vorhandene Zeitstempel der Sitzungsbeitraege.

    Die Zeitstempel stammen aus den Beitraegen der Sitzung selbst
    (``timestamp`` je user-/assistant-Eintrag), nie aus Datei- oder
    Exportdaten. Ein fehlender Zeitstempel bleibt fehlend.
    """
    rows, stamps = [], []
    seen: set[str] = set()
    parents: list[str] = []
    pending = False
    for number, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        entry = _parse(
            raw, number, number == len(lines), ends_with_newline
        )
        _validate(_ENVELOPE, entry, number)
        stats["records"] += 1
        _check_lineage(entry, number, seen, parents)
        if entry["type"] not in {"user", "assistant"}:
            continue
        _validate(_MESSAGE, entry, number)
        _check_message(entry, number, session_id)
        if "timestamp" in entry:
            stamps.append(entry["timestamp"])
        else:
            stats["records_without_timestamp"] += 1
        result = _classify(entry, number, stats)
        if result is None:
            continue
        role, text, phase = result
        if not text.strip():
            raise _fail(number, "leerer Transkripttext")
        if role == "user":
            if pending:
                stats[
                    "human_inputs_without_final_before_next_input"
                ] += 1
            pending = True
        elif phase == "final":
            pending = False
        if role == "assistant":
            stats[f"{phase}_text_records"] += 1
            if phase != "final":
                continue
        rows.append((number, role, text, entry.get("timestamp")))
    stats["human_input_pending_at_eof"] = int(pending)
    stats["branch_points"] = sum(
        n > 1 for n in Counter(parents).values()
    )
    if not rows:
        raise TranscriptError(("keine Transkriptbeitraege gefunden",))
    return rows, stamps


def _parse(raw: str, number: int, last: bool, ends_with_newline: bool):
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        partial = last and not ends_with_newline
        raise _fail(
            number,
            "ungueltiges JSON"
            + (
                " (letzte Zeile, evtl. unvollstaendig)"
                if partial
                else ""
            ),
        ) from None


def _validate(validator, entry: object, number: int) -> None:
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
    raise _fail(number, f"ungueltiges Feld {path} ({rule})")


def _check_lineage(
    entry: dict, number: int, seen: set[str], parents: list[str]
) -> None:
    if "uuid" not in entry:
        return
    if entry["uuid"] in seen:
        raise _fail(number, "doppelte uuid")
    parent = entry.get("parentUuid")
    if parent is not None and parent not in seen:
        raise _fail(number, "parentUuid fehlt oder steht nicht davor")
    seen.add(entry["uuid"])
    if parent is not None:
        parents.append(parent)


def _check_message(entry: dict, number: int, session_id: str) -> None:
    # Deckt auch gemischte Sitzungen ab; der Wert bleibt ungenannt.
    if entry["sessionId"] != session_id:
        raise _fail(
            number, "sessionId passt nicht zur angeforderten Sitzung"
        )
    if entry["message"]["role"] != entry["type"]:
        raise _fail(number, "type und message.role widersprechen sich")
    if "timestamp" in entry and not is_timestamp(entry["timestamp"]):
        raise _fail(number, "ungueltiges Feld timestamp (Datum)")


def _classify(
    entry: dict, number: int, stats: Counter[str]
) -> tuple[str, str, str] | None:
    if entry["isSidechain"] or entry.get("isMeta", False):
        stats["sidechain_or_meta_excluded"] += 1
        return None
    if entry["type"] == "user":
        return _classify_user(entry, number, stats)
    return _classify_assistant(entry, number, stats)


def _classify_user(
    entry: dict, number: int, stats: Counter[str]
) -> tuple[str, str, str] | None:
    content = entry["message"]["content"]
    if _TASK_NOTIFICATION.is_valid(entry):
        stats["task_notifications_excluded"] += 1
        return None
    if _COMPACT_SUMMARY.is_valid(entry):
        stats["compact_summaries_excluded"] += 1
        return None
    if entry.get("origin", {}).get("kind") == "human":
        return "user", _human_text(entry, number), "input"
    if _is_local_command(entry, content):
        stats["local_commands_excluded"] += 1
        return None
    if "interruptedMessageId" in entry:
        stats["interruption_markers"] += 1
        return None
    if (
        isinstance(content, list)
        and content
        and all(block["type"] == "tool_result" for block in content)
    ):
        stats["tool_results_excluded"] += 1
        return None
    raise _fail(
        number,
        "user-Beitrag ohne belegte menschliche Herkunft "
        + _describe(entry),
    )


def _is_local_command(entry: dict, content: object) -> bool:
    """Slash-Befehl samt Ausgabe: fuehrender Befehls-Tag und keinerlei
    Herkunftsangabe (so schreibt Claude diese Zeilen). Ein Tag allein
    belegt nichts; ein menschliches Zitat mit Tag bleibt Eingabe."""
    unmarked = not any(
        key in entry for key in ("origin", "turnOrigin", "promptSource")
    )
    return (
        unmarked
        and isinstance(content, str)
        and content.lstrip().startswith(_LOCAL_COMMAND_PREFIXES)
    )


def _human_text(entry: dict, number: int) -> str:
    # Aeltere Claude-Versionen schreiben turnOrigin nicht; die Herkunft
    # belegen dann origin.kind und promptSource allein.
    turn_origin = entry.get("turnOrigin", _MISSING)
    if turn_origin not in {_MISSING, "human"} or entry.get(
        "promptSource"
    ) not in {"typed", "queued"}:
        raise _fail(
            number,
            "unbekannte menschliche Herkunftsmarkierung "
            + _describe(entry),
        )
    content = entry["message"]["content"]
    if not isinstance(content, str):
        raise _fail(
            number,
            "menschlicher Inhalt ist kein String " + _describe(entry),
        )
    return content


def _classify_assistant(
    entry: dict, number: int, stats: Counter[str]
) -> tuple[str, str, str] | None:
    message = entry["message"]
    if message.get("model") == "<synthetic>" or entry.get(
        "isApiErrorMessage", False
    ):
        stats["synthetic_or_error_excluded"] += 1
        return None
    content = message["content"]
    if not isinstance(content, list):
        raise _fail(
            number,
            "assistant-Inhalt ist keine Blockliste " + _describe(entry),
        )
    texts = [
        block["text"] for block in content if block["type"] == "text"
    ]
    if not texts:
        stats["non_text_assistant_excluded"] += 1
        return None
    reason = message.get("stop_reason")
    if reason not in {"end_turn", "tool_use"}:
        raise _fail(
            number,
            "unbelegter stop_reason fuer assistant-Text "
            + _describe(entry),
        )
    phase = "final" if reason == "end_turn" else "commentary"
    return "assistant", "\n".join(texts), phase


def _describe(entry: dict) -> str:
    """Inhaltsfreie Strukturbeschreibung eines Beitrags."""
    message = entry["message"]
    fields = {"isMeta": _marker(entry.get("isMeta", _MISSING))}
    if entry["type"] == "user":
        origin = entry.get("origin", _MISSING)
        kind = _MISSING if origin is _MISSING else origin["kind"]
        fields |= {
            "origin.kind": _marker(kind),
            "turnOrigin": _marker(entry.get("turnOrigin", _MISSING)),
            "promptSource": _marker(
                entry.get("promptSource", _MISSING)
            ),
            "userType": _marker(entry.get("userType", _MISSING)),
        }
    else:
        fields["stop_reason"] = _marker(
            message.get("stop_reason", _MISSING)
        )
    fields["content"] = _content_shape(message["content"])
    return "(" + ", ".join(f"{k}={v}" for k, v in fields.items()) + ")"


def _marker(value: object) -> str:
    """Bekannte Kennzeichen woertlich; alles andere nur als Typ."""
    if value is _MISSING:
        return "<fehlt>"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, str) and value in _KNOWN_MARKERS:
        return value
    return f"<{type(value).__name__}>"


def _content_shape(content: object) -> str:
    """str, str<tag> bei bekanntem fuehrendem Tag, sonst Blocktypen."""
    if isinstance(content, str):
        stripped = content.lstrip()
        tag = next(
            (
                t
                for t in sorted(_KNOWN_TAGS)
                if stripped.startswith(f"<{t}>")
            ),
            None,
        )
        return f"str<{tag}>" if tag else "str"
    kinds = sorted({_marker(block["type"]) for block in content})
    return "[" + ",".join(kinds) + "]"
