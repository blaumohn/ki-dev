"""Inhaltsklassifikation und sichere Diagnosen für Claude-Beiträge."""

from collections import Counter

from .claude_transcript_schema import (
    ASSISTANT_TEXT,
    ASSISTANT_TEXT_PHASES,
    COMPACT_SUMMARY,
    TASK_NOTIFICATION,
    line_error,
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

# Unterbrechungsmarke: Claude schreibt sie teils mit
# ``interruptedMessageId``, teils ohne jede Herkunftsangabe als einzigen
# Textblock.
_INTERRUPTION_TEXTS = frozenset(
    {
        "[Request interrupted by user]",
        "[Request interrupted by user for tool use]",
    }
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


def classify_content(
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
    if TASK_NOTIFICATION.is_valid(entry):
        stats["task_notifications_excluded"] += 1
        return None
    if COMPACT_SUMMARY.is_valid(entry):
        stats["compact_summaries_excluded"] += 1
        return None
    if entry.get("origin", {}).get("kind") == "human":
        return "user", _human_text(entry, number), "input"
    excluded = _excluded_user_record(entry, content)
    if excluded is not None:
        stats[excluded] += 1
        return None
    raise line_error(
        number,
        "user-Beitrag ohne belegte menschliche Herkunft "
        + _describe(entry),
    )


def _excluded_user_record(entry: dict, content: object) -> str | None:
    if _is_local_command(entry, content):
        return "local_commands_excluded"
    if "interruptedMessageId" in entry or _is_interruption_text(
        entry, content
    ):
        return "interruption_markers"
    if (
        isinstance(content, list)
        and content
        and all(block["type"] == "tool_result" for block in content)
    ):
        return "tool_results_excluded"
    return None


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


def _is_interruption_text(entry: dict, content: object) -> bool:
    """Unterbrechungsmarke ohne jede Herkunftsangabe: genau ein
    Textblock mit bekanntem Wortlaut. Ein menschliches Zitat traegt
    Herkunftsfelder und bleibt Eingabe."""
    unmarked = not any(
        key in entry for key in ("origin", "turnOrigin", "promptSource")
    )
    return (
        unmarked
        and isinstance(content, list)
        and len(content) == 1
        and content[0]["type"] == "text"
        and content[0]["text"] in _INTERRUPTION_TEXTS
    )


def _human_text(entry: dict, number: int) -> str:
    # Aeltere Claude-Versionen schreiben turnOrigin nicht; die Herkunft
    # belegen dann origin.kind und promptSource allein.
    turn_origin = entry.get("turnOrigin", _MISSING)
    if turn_origin not in {_MISSING, "human"} or entry.get(
        "promptSource"
    ) not in {"typed", "queued"}:
        raise line_error(
            number,
            "unbekannte menschliche Herkunftsmarkierung "
            + _describe(entry),
        )
    content = entry["message"]["content"]
    if not isinstance(content, str):
        raise line_error(
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
        raise line_error(
            number,
            "assistant-Inhalt ist keine Blockliste " + _describe(entry),
        )
    texts = [
        block["text"] for block in content if block["type"] == "text"
    ]
    if not texts:
        stats["non_text_assistant_excluded"] += 1
        return None
    if not ASSISTANT_TEXT.is_valid(message):
        raise line_error(
            number,
            "unbelegtes Feld message.stop_reason fuer assistant-Text "
            + _describe(entry),
        )
    phase = ASSISTANT_TEXT_PHASES[message["stop_reason"]]
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
        marker = "<fehlt>"
    elif value is None:
        marker = "null"
    elif isinstance(value, bool):
        marker = str(value).lower()
    elif isinstance(value, str) and value in _KNOWN_MARKERS:
        marker = value
    else:
        marker = f"<{type(value).__name__}>"
    return marker


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
