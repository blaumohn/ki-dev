"""Kommandozeile fuer ki-dev.

``ki-dev -f NAME …`` fährt ein Ablaufpaket (wie ``make -f``): NAME wird
gesucht (:mod:`ki_dev.flow.package`), das ``ops``-Modul des Ablaufs
liefert die Befehle. Die übrigen Befehle sind Werkzeuge daneben.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import NoReturn

import typer
from rich.console import Console
from rich.text import Text

from ki_dev.config_cli import config
from ki_dev.flow.model import FlowError, load_flow_file
from ki_dev.flow.package import find_flow
from ki_dev.flow_cli import app as flow_app
from ki_dev.flow_ops import load_ops
from ki_dev.planning_cli import app as planning_app
from ki_dev.session_cli import app as session_app
from ki_dev.step.cli import handoff

FILE_OPTIONS = ("-f", "--file")
_HELP_WORDS = ("--help", "-h")

errors = Console(stderr=True)

app = typer.Typer(
    help=(
        "ki-dev - deklarative Abläufe, ein Ausführer, austauschbare "
        "Agentenadapter."
    ),
    epilog=(
        "Abläufe: ki-dev -f NAME [BEFEHL] … sucht ./NAME.toml, "
        "$KI_DEV_FLOW_PATH, dann das mitgelieferte Paket. "
        "Beispiel: ki-dev -f implement BEAD --adapter review=manual"
    ),
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(flow_app, name="flow")
app.add_typer(planning_app, name="planning")
app.add_typer(session_app, name="session")
app.command("step")(handoff)
app.command("config")(config)


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if args[:1] and args[0] in FILE_OPTIONS:
        run_flow(args[1:])
    else:
        app(args=args, prog_name="ki-dev")


def run_flow(args: list[str]) -> None:
    """``ki-dev -f NAME [BEFEHL] …``: ohne BEFEHL gilt der erste
    Befehl des Pakets (bei implement: start)."""
    if not args:
        _abort("-f braucht den Namen oder Pfad eines Ablaufs")
    name, rest = args[0], args[1:]
    try:
        path = find_flow(name, Path.cwd(), os.environ)
        flow = load_flow_file(path)
        command = typer.main.get_command(load_ops(flow, path))
    except FlowError as exc:
        _abort(f"Ablauffehler: {exc}")
    errors.print(Text(f"Ablauf: {path}", style="dim"))
    names = list(getattr(command, "commands", {}))
    if rest and rest[0] not in names and rest[0] not in _HELP_WORDS:
        rest = [names[0], *rest]
    command.main(args=rest, prog_name=f"ki-dev -f {name}")


def _abort(message: str) -> NoReturn:
    errors.print(Text(message, style="red"))
    raise SystemExit(2)
