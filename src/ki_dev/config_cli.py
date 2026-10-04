"""Typer-Anbindung für ki-dev config."""

from __future__ import annotations

from pathlib import Path

import typer

from ki_dev import handoff_preflight, loop_cli, tool_versions
from ki_dev.config_sources import ConfigSource

# Reihenfolge der Ausgabe; die Orte selbst definieren die Module.
SOURCES = (
    handoff_preflight.CONFIG_SOURCE,
    loop_cli.CONFIG_SOURCE,
    tool_versions.CONFIG_SOURCE,
)

_HEADER = ("BEFEHL", "ORT", "ABSCHNITT", "ZUSTAND")


def config() -> None:
    """Konfigurationsorte der ki-dev-Befehle auflisten.

    Bezogen auf das aktuelle Verzeichnis; geprüft wird nur, ob eine
    Datei vorhanden ist, nicht ihr Inhalt.
    """
    rows = [_HEADER, *(_row(source, Path.cwd()) for source in SOURCES)]
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    for row in rows:
        cells = [
            cell.ljust(width)
            for cell, width in zip(row, widths, strict=False)
        ]
        typer.echo("  ".join([*cells, row[3]]))


def _row(source: ConfigSource, cwd: Path) -> tuple[str, str, str, str]:
    return (
        source.command,
        source.location,
        source.section or "-",
        _state(source, cwd),
    )


def _state(source: ConfigSource, cwd: Path) -> str:
    if source.path is None:
        return "je Aufruf"
    return "vorhanden" if (cwd / source.path).is_file() else "fehlt"
