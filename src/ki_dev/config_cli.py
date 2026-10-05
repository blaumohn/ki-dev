"""Typer-Anbindung für ki-dev config."""

from __future__ import annotations

from pathlib import Path

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from ki_dev import (
    handoff_limit_config,
    handoff_next_turn,
    handoff_preflight,
    loop_cli,
    tool_versions,
)
from ki_dev.config_sources import ConfigSource

# Reihenfolge der Ausgabe; die Orte selbst definieren die Module.
SOURCES = (
    handoff_preflight.CONFIG_SOURCE,
    handoff_limit_config.CONFIG_SOURCE,
    handoff_next_turn.CONFIG_SOURCE,
    loop_cli.CONFIG_SOURCE,
    tool_versions.CONFIG_SOURCE,
)

_STATE_STYLES = {
    "vorhanden": "green",
    "fehlt": "red",
    "je Aufruf": "dim",
}

console = Console()


def config() -> None:
    """Konfigurationsorte der ki-dev-Befehle auflisten.

    Bezogen auf das aktuelle Verzeichnis; geprüft wird nur, ob eine
    Datei vorhanden ist, nicht ihr Inhalt.
    """
    table = Table(box=box.SIMPLE_HEAD, show_edge=False, pad_edge=False)
    table.add_column("Befehl", style="bold", overflow="fold")
    # Pfade vollständig umbrechen statt mit … abschneiden.
    table.add_column("Ort / Abschnitt", overflow="fold")
    table.add_column("Zustand", no_wrap=True)
    for source in SOURCES:
        table.add_row(*_row(source, Path.cwd()))
    console.print(table)


def _row(source: ConfigSource, cwd: Path) -> tuple[Text, Text, Text]:
    # Text statt Markup-Zeichenketten: Abschnitte wie
    # [tool.ki-dev.handoff.preflight] dürfen nicht als Rich-Markup
    # gelesen werden.
    location = Text(source.location)
    if source.section:
        location.append(f"\n[{source.section}]", style="cyan")
    state = _state(source, cwd)
    return (
        Text(source.command),
        location,
        Text(state, style=_STATE_STYLES[state]),
    )


def _state(source: ConfigSource, cwd: Path) -> str:
    if source.path is None:
        return "je Aufruf"
    return "vorhanden" if (cwd / source.path).is_file() else "fehlt"
