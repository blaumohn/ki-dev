"""Commands for immutable planning deltas."""

from pathlib import Path
from typing import Annotated

import typer

from ki_dev import planning

app = typer.Typer(help="Planungsdeltas prüfen, ablegen und auflösen.")
Store = Annotated[Path, typer.Option(help="Verzeichnis der Schrittdeltas.")]
Root = Annotated[Path, typer.Option(help="Wurzel der relativen Quellenpfade.")]


def _run(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (planning.PlanningError, OSError) as exc:
        typer.echo(f"Planungsfehler: {exc}", err=True)
        raise typer.Exit(1) from exc


@app.command("check")
def check(
    store: Store = Path("planning/steps"), root: Root = Path("."),
    candidate: Annotated[Path | None, typer.Option()] = None,
):
    """Historie und Quellen prüfen; optional ein neues Delta prüfen."""
    state = _run(planning.resolve, store, root=root)
    if candidate is not None:
        delta = _run(planning.read_json, candidate)
        state = _run(planning.apply_delta, state, delta, root=root)
    typer.echo(f"OK: Schritt {state['step']}, {len(state['nodes'])} Knoten")


@app.command("append")
def append(
    candidate: Path, store: Store = Path("planning/steps"),
    root: Root = Path("."),
):
    """Geprüftes Delta als neue unveränderliche Schrittdatei ablegen."""
    state = _run(planning.append, store, candidate, root)
    typer.echo(f"Schritt {state['step']}: {state['head']}")


@app.command("resolve")
def resolve(
    store: Store = Path("planning/steps"),
    at: Annotated[int | None, typer.Option(min=0)] = None,
    markdown: Annotated[bool, typer.Option()] = False,
):
    """Planungsstand als JSON oder Markdown auf stdout erzeugen."""
    state = _run(planning.resolve, store, at=at)
    output = planning.render(state) if markdown else planning.encode(state).decode()
    typer.echo(output, nl=False)


@app.command("source")
def source(
    path: str, start: int, end: int, root: Root = Path("."),
):
    """Quellenverweis mit Dateihash und Zeilenbereich erzeugen."""
    ref = _run(planning.source_ref, root, path, start, end)
    typer.echo(planning.encode(ref).decode(), nl=False)


@app.command("schema")
def schema():
    """Das verbindliche Delta-JSON-Schema ausgeben."""
    typer.echo(planning.encode(planning.DELTA_SCHEMA).decode(), nl=False)
