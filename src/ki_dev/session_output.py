"""Ausgabegrenze von ``ki-dev session``: Terminal, Pager, Datei.

Der Pager ist der eingebaute von Rich (``Console.pager``, ueber
``pydoc.pager``). Ausnahme zur Technikleitlinie siehe dort
(Abschnitt Ausnahmen): ``pydoc`` startet ``$PAGER`` ueber die Shell.
"""

from __future__ import annotations

import contextlib
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

import typer
from rich.console import Console, RenderableType

_LESS_RAW = re.compile(r"(?:^|\s)-\S*[rR]")


class OutputExistsError(RuntimeError):
    """--output zeigt auf eine vorhandene Datei (nie ueberschreiben)."""


def print_rich(renderable: RenderableType, *, pager: bool) -> None:
    """Am Terminal farbig, optional im Pager; umgeleitet ohne ANSI.

    Schliesst der Leser die Ausgabe frueh (``| head``), ist das ein
    erwarteter Abbruch ohne Fehlermeldung.
    """
    console = Console(highlight=False)
    try:
        if pager and console.is_terminal:
            with (
                _less_keeps_colors(),
                console.pager(styles=True, links=False),
            ):
                console.print(renderable)
        else:
            console.print(renderable)
    except BrokenPipeError:
        silence_stdout()


def fail(message: str, *, code: int) -> NoReturn:
    """Diagnose nach stderr, dann Exit mit ``code``."""
    typer.echo(message, err=True)
    raise typer.Exit(code=code)


def write_bytes(data: bytes, output: Path | None) -> None:
    """Saubere Ausgabe auf stdout oder in eine neue Datei."""
    if output is None:
        try:
            stream = sys.stdout.buffer
            stream.write(data)
            stream.flush()
        except BrokenPipeError:
            silence_stdout()
        return
    try:
        with output.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        raise OutputExistsError(
            f"{output.name} existiert bereits; nichts geschrieben"
        ) from None


def silence_stdout() -> None:
    """Nach geschlossener Leseseite stdout auf devnull lenken, damit
    das Beenden des Interpreters keinen zweiten Schreibfehler meldet."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, sys.stdout.fileno())


@contextlib.contextmanager
def _less_keeps_colors() -> Iterator[None]:
    """``less`` zeigt Rich-Farben nur mit ``-R``; LESS wird nur fuer
    die Dauer des Pagers ergaenzt und danach wiederhergestellt."""
    command = os.environ.get("MANPAGER") or os.environ.get("PAGER")
    program = (command or "less").split() or ["less"]
    previous = os.environ.get("LESS")
    if Path(program[0]).name != "less" or _LESS_RAW.search(
        previous or ""
    ):
        yield
        return
    os.environ["LESS"] = f"{previous or ''} -R".strip()
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("LESS", None)
        else:
            os.environ["LESS"] = previous
