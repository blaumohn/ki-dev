"""Kommandozeile fuer ki-dev.

Dieser Schnitt stellt nur die Befehlsoberflaeche bereit: ``ki-dev loop``
und ``ki-dev loop resume`` sind verkabelbare Einstiegspunkte, die
absichtlich noch keinen Lauf ausfuehren.
"""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()

app = typer.Typer(
    help="ki-dev - begrenzte deterministische Agentenmaschine.",
    no_args_is_help=True,
    add_completion=False,
)
loop_app = typer.Typer(
    help="Einen ki-dev-Lauf starten oder fortsetzen.",
)
app.add_typer(loop_app, name="loop")

_NOT_WIRED = (
    "Die Agentenschleife ist in diesem Schnitt noch nicht verkabelt "
    "(siehe ki-dev-ablauf-8dd.4)."
)


def main() -> None:
    app()


@loop_app.callback(invoke_without_command=True)
def loop(ctx: typer.Context) -> None:
    """Einen neuen ki-dev-Lauf starten."""
    if ctx.invoked_subcommand is None:
        _abort_not_wired()


@loop_app.command()
def resume() -> None:
    """Einen pausierten ki-dev-Lauf fortsetzen."""
    _abort_not_wired()


def _abort_not_wired() -> None:
    console.print(f"[yellow]{_NOT_WIRED}[/yellow]")
    raise typer.Exit(code=1)
