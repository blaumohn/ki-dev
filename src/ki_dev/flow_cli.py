"""Kommandozeile ``ki-dev flow``: mitgelieferte Abläufe zeigen."""

from __future__ import annotations

from typing import Annotated

import typer

from ki_dev.flow.diagram import render_mermaid
from ki_dev.flow.model import FlowError, load_flow

app = typer.Typer(
    help="Mitgelieferte Abläufe (flow/*.toml) zeigen.",
    no_args_is_help=True,
)


@app.command("show")
def show(
    name: Annotated[
        str,
        typer.Argument(help="Ablauf, z. B. delivery oder planning."),
    ],
    without_escalations: Annotated[
        bool,
        typer.Option(
            "--without-escalations",
            help="Kanten mit escalation (Grenz- und Schutzhalte) "
            "ausblenden.",
        ),
    ] = False,
) -> None:
    """Ablauf als Mermaid-Zustandsdiagramm ausgeben."""
    try:
        flow = load_flow(name)
    except FlowError as exc:
        typer.echo(f"Ablauffehler: {exc}", err=True)
        raise typer.Exit(2) from exc
    typer.echo(
        render_mermaid(flow, without_escalations=without_escalations),
        nl=False,
    )
