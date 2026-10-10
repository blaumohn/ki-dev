"""Ops der Ablaufpakete: was ``ki-dev -f NAME`` für einen Ablauf tut.

Ein Ablauf nennt in ``ops`` das Modul, das seine Operationen umsetzt.
Das Modul stellt ``commands(flow, path)`` bereit: eine Typer-Anwendung
mit den Befehlen des Pakets. Der erste Befehl ist der Standard
(``ki-dev -f implement BEAD`` = ``… start BEAD``).

Diese Schicht liegt über Ausführer, Ops-Bausteinen und Adaptern; sie
steckt zusammen, was ein Paket braucht.
"""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Protocol

import typer

from ki_dev.flow.model import Flow, FlowError


class FlowOps(Protocol):
    def commands(self, flow: Flow, path: Path) -> typer.Typer: ...


def load_ops(flow: Flow, path: Path) -> typer.Typer:
    """Befehle des Pakets; ein Ablauf ohne ``ops`` ist nur Daten."""
    if flow.ops is None:
        raise FlowError(
            f"{path}: kein ops-Modul; der Ablauf ist nur Daten "
            f"(ki-dev flow show {flow.name})"
        )
    try:
        module = import_module(flow.ops)
    except ImportError as exc:
        raise FlowError(
            f"{path}: ops-Modul {flow.ops} nicht ladbar ({exc})"
        ) from exc
    commands = getattr(module, "commands", None)
    if not callable(commands):
        raise FlowError(
            f"{path}: ops-Modul {flow.ops} ohne commands(flow, path)"
        )
    return commands(flow, path)
