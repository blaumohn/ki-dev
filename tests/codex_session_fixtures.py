"""Kleine synthetische Codex-Sitzungen (keine echten Inhalte)."""

import json
from pathlib import Path

SECRET = "SENTINEL-GEHEIMER-GESPRAECHSINHALT"


def user(ordinal, turn="t1", text="Frage", **overrides):
    entry = {
        "type": "event_msg",
        "ordinal": ordinal,
        "payload": {
            "type": "item_completed",
            "turn_id": turn,
            "item": {
                "type": "UserMessage",
                "content": [{"type": "text", "text": text}],
            },
        },
    }
    return entry | overrides


def assistant(ordinal, turn="t1", text="Antwort", phase="final_answer"):
    return {
        "type": "response_item",
        "ordinal": ordinal,
        "payload": {
            "type": "message",
            "role": "assistant",
            "phase": phase,
            "internal_chat_message_metadata_passthrough": {
                "turn_id": turn
            },
            "content": [{"type": "output_text", "text": text}],
        },
    }


def noise():
    """Bekannte irrelevante Ereignisse."""
    return [
        {"type": "turn_context", "payload": {"cwd": "/x"}},
        {"type": "event_msg", "payload": {"type": "token_count"}},
        {
            "type": "response_item",
            "payload": {"type": "function_call", "name": "f"},
        },
    ]


def dialog(pairs=2):
    rows = []
    for index in range(pairs):
        turn = f"t{index}"
        rows.append(user(2 * index + 1, turn, f"Frage {index}"))
        rows.append(assistant(2 * index + 2, turn, f"Antwort {index}"))
    return rows


def jsonl(rows):
    return "".join(json.dumps(row) + "\n" for row in rows)


def write_session(root: Path, session_id: str, rows, day="2026/09/17"):
    directory = root / day
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"rollout-2026-09-17T09-10-35-{session_id}.jsonl"
    path.write_text(jsonl(rows), encoding="utf-8")
    return path
