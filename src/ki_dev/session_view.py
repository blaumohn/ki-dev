"""Anzeige normalisierter Transkripte: Rich-Renderables und Markdown.

Reine Umwandlung ohne Ein-/Ausgabe; Rohsitzung und Snapshot kommen
ueber denselben Vertrag (``SessionTranscript``) hierher.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from rich import box
from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from ki_dev.adapter.executors.session_catalog import SessionRef
from ki_dev.adapter.executors.session_transcript import (
    SessionTranscript,
    TranscriptMessage,
)

_ROLE_LABELS = {"user": "Mensch", "assistant": "Agent"}
PREVIEW_CHARS = 60


@dataclass(frozen=True)
class ListEntry:
    """Eine Zeile der Liste: gelesenes Transkript oder Prüfcodes."""

    ref: SessionRef
    transcript: SessionTranscript | None
    problems: tuple[str, ...] = ()


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


def listing_renderable(entries: Sequence[ListEntry]) -> Table:
    """Nummerierte Liste: Anbieter, Zeit, ID und Vorschau je Sitzung."""
    table = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False)
    table.add_column("Nr", justify="right", style="bold")
    table.add_column("Sitzung", no_wrap=True)
    table.add_column("Vorschau", overflow="fold")
    for number, entry in enumerate(entries, 1):
        table.add_row(
            str(number),
            _session_cell(entry),
            _preview_cell(entry),
        )
    return table


def _session_cell(entry: ListEntry) -> Text:
    """Anbieter und letzte Aktivität, darunter die ganze ID."""
    cell = Text(f"{entry.ref.agent} · ")
    cell.append(_last_activity(entry.transcript))
    cell.append(f"\n{entry.ref.session_id}", style="dim")
    return cell


def _last_activity(transcript: SessionTranscript | None) -> str:
    stamp = transcript.last_activity_at if transcript else None
    if stamp is None:
        return "—"
    local = datetime.fromisoformat(stamp).astimezone()
    return f"{local:%Y-%m-%d %H:%M}"


def _preview_cell(entry: ListEntry) -> Text:
    if entry.transcript is None:
        problems = "; ".join(entry.problems)
        return Text(f"nicht verwendbar: {problems}", style="red")
    cell = Text()
    for role in ("user", "assistant"):
        if cell:
            cell.append("\n")
        cell.append(f"{_ROLE_LABELS[role]}: ", style="dim")
        cell.append(_preview(entry.transcript, role))
    return cell


def _preview(transcript: SessionTranscript, role: str) -> str:
    """Erster Beitrag der Rolle, einzeilig und gekürzt."""
    for message in transcript.messages:
        if message.role == role:
            flat = " ".join(message.text.split())
            if len(flat) <= PREVIEW_CHARS:
                return flat
            return flat[: PREVIEW_CHARS - 1] + "…"
    return "—"
