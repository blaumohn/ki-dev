"""Anbieterübergreifende Metadaten aus dem Rohvorspann lesen."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SessionHeader:
    cwd: str | None = None
    subagent: bool = False
    first_user_text: str | None = None


def read_session_header(agent: str, path: Path) -> SessionHeader:
    """Unbekannter Vorspann bleibt für die Dialogprüfung ungeklärt."""
    cwd = None
    subagent = False
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                row = json.loads(line)
                if not isinstance(row, dict):
                    return SessionHeader()
                meta = row.get("payload") if agent == "codex" else row
                if isinstance(meta, dict):
                    if cwd is None and isinstance(meta.get("cwd"), str):
                        cwd = meta["cwd"]
                    source = meta.get("source")
                    if (
                        isinstance(source, dict)
                        and "subagent" in source
                    ):
                        subagent = True
                text = _user_text(agent, row)
                if text is not None:
                    return SessionHeader(cwd, subagent, text)
    except (OSError, UnicodeError, json.JSONDecodeError):
        # Unklassifiziert lassen; die Dialogprüfung meldet Lesefehler.
        return SessionHeader()
    return SessionHeader(cwd, subagent)


def _user_text(agent: str, row: dict) -> str | None:
    if agent == "claude":
        if row.get("type") != "user" or row.get("isMeta"):
            return None
        message = row.get("message")
    else:
        payload = row.get("payload")
        if not isinstance(payload, dict):
            return None
        if row.get("type") != "event_msg":
            return None
        if payload.get("type") == "user_message":
            text = payload.get("message")
            return text if isinstance(text, str) else None
        message = payload.get("item")
        if not isinstance(message, dict):
            return None
        if message.get("type") != "UserMessage":
            return None
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = [
            part["text"]
            for part in content
            if isinstance(part, dict)
            and part.get("type") in ("text", "input_text")
            and isinstance(part.get("text"), str)
        ]
        if texts:
            return "\n".join(texts)
    return None
