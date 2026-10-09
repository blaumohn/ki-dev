"""Abbruch mit Exitcode: Meldung auf stderr, keine Ausgabe."""

from __future__ import annotations

from typing import NoReturn

import typer


def fail(message: str, *, code: int) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)
