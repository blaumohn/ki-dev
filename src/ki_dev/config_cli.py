"""Typer-Anbindung für ki-dev config."""

from __future__ import annotations

from pathlib import Path

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from ki_dev import tool_versions
from ki_dev.config_sources import ConfigSource
from ki_dev.flow import package
from ki_dev.flow_ops.implement import cli as runner_cli
from ki_dev.ops.checks import preflight
from ki_dev.ops.context import limit_config
from ki_dev.step import feedback

# Reihenfolge der Ausgabe; die Orte selbst definieren die Module.
SOURCES = (
    preflight.CONFIG_SOURCE,
    limit_config.CONFIG_SOURCE,
    feedback.CONFIG_SOURCE,
    package.CONFIG_SOURCE,
    runner_cli.CONFIG_SOURCE,
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
