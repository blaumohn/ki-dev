"""Kleine synthetische Claude-Sitzungen (keine echten Inhalte)."""

import json
from pathlib import Path

SESSION = "1c0aaaaa-bbbb-cccc-dddd-eeeeffff0002"


def human(text="Frage", **overrides):
    entry = {
        "type": "user",
        "origin": {"kind": "human"},
        "turnOrigin": "human",
        "promptSource": "typed",
        "message": {"role": "user", "content": text},
    }
    return entry | overrides


def reply(text="Antwort", stop_reason="end_turn"):
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "model": "claude-test",
            "stop_reason": stop_reason,
            "content": [{"type": "text", "text": text}],
        },
    }


def task_notification(
    text="<task-notification>fertig</task-notification>",
):
    return {
        "type": "user",
        "origin": {"kind": "task-notification"},
        "turnOrigin": "task_notification",
        "promptSource": "system",
        "message": {"role": "user", "content": text},
    }


def compact_summary(text="This session is being continued ..."):
    """Verdichtungszusammenfassung, wie Claude sie schreibt."""
    return {
        "type": "user",
        "userType": "external",
        "isVisibleInTranscriptOnly": True,
        "isCompactSummary": True,
        "message": {"role": "user", "content": text},
    }


def local_command(text="<command-name>/model</command-name>"):
    """Slash-Befehlszeile, wie Claude sie schreibt: ohne Herkunft."""
    return {
        "type": "user",
        "userType": "external",
        "message": {"role": "user", "content": text},
    }


def interruption(text="[Request interrupted by user]"):
    """Unterbrechungsmarke, wie Claude sie schreibt: ohne Herkunft."""
    return {
        "type": "user",
        "userType": "external",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    }


def tool_result():
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t",
                    "content": "x",
                }
            ],
        },
    }


def chain(entries, start_second=0):
    """uuid-Kette, sessionId und Zeitstempel ergaenzen."""
    rows, parent = [], None
    for index, entry in enumerate(entries, 1):
        second = start_second + index
        row = {
            "uuid": f"u{index}",
            "parentUuid": parent,
            "sessionId": SESSION,
            "timestamp": f"2026-10-05T10:00:{second:02d}.000Z",
            "isSidechain": False,
        } | entry
        rows.append(row)
        parent = row["uuid"]
    return rows


def dialog(pairs=2):
    entries = []
    for index in range(pairs):
        entries += [human(f"Frage {index}"), reply(f"Antwort {index}")]
    return chain(entries)


def jsonl(rows):
    return "".join(json.dumps(row) + "\n" for row in rows)


def write_session(
    root: Path, session_id: str, rows, project="-workspace"
):
    directory = root / project
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session_id}.jsonl"
    path.write_text(jsonl(rows), encoding="utf-8")
    return path
