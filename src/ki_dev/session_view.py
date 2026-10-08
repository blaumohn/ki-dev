"""Anzeige normalisierter Transkripte: Rich-Renderables und Markdown.

Reine Umwandlung ohne Ein-/Ausgabe; Rohsitzung und Snapshot kommen
ueber denselben Vertrag (``SessionTranscript``) hierher.
"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.rule import Rule
from rich.text import Text

from ki_dev.adapter.executors.session_transcript import (
    SessionTranscript,
    TranscriptMessage,
)

_ROLE_LABELS = {"user": "Mensch", "assistant": "Agent"}


def heading(transcript: SessionTranscript, title: str | None) -> str:
    return (
        title or f"{transcript.agent}-Sitzung {transcript.session_id}"
    )


def subtitle(transcript: SessionTranscript) -> str:
    """Anbieter, Sitzung und Zeit; fehlende Zeiten als ``—``."""
    started = transcript.started_at or "—"
    last = transcript.last_activity_at or "—"
    return (
        f"{transcript.agent} · {transcript.session_id} · "
        f"Beginn {started} · zuletzt {last} · "
        f"{len(transcript.messages)} Beiträge"
    )


def transcript_renderable(
    transcript: SessionTranscript, title: str | None
) -> RenderableType:
    """Kopf einmal, danach Rolle und Markdown je Beitrag."""
    parts: list[RenderableType] = [
        Text(heading(transcript, title), style="bold"),
        Text(subtitle(transcript), style="dim"),
    ]
    for message in transcript.messages:
        parts.append(Text())
        parts.append(Rule(Text(_message_label(message)), align="left"))
        parts.append(Markdown(message.text, code_theme="ansi_dark"))
    return Group(*parts)


def transcript_markdown(
    transcript: SessionTranscript, title: str | None
) -> str:
    """Derselbe Inhalt als Markdown; Beitragstexte unverändert."""
    blocks = [
        f"# {heading(transcript, title)}",
        f"_{subtitle(transcript)}_",
    ]
    for message in transcript.messages:
        blocks.append(f"## {_message_label(message)}")
        blocks.append(message.text)
    return "\n\n".join(blocks) + "\n"


def _message_label(message: TranscriptMessage) -> str:
    role = _ROLE_LABELS.get(message.role, message.role)
    stamp = f" · {message.timestamp}" if message.timestamp else ""
    return f"{message.position} {role}{stamp}"
