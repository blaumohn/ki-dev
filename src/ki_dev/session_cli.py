"""Kommandozeile ``ki-dev session``: Sitzungen als Snapshot ablegen.

Auswahl nur per expliziter ID und Anbieter; Suche gehoert zu 70u.3.
Diagnosen gehen ausschliesslich nach stderr und nennen nie Inhalte.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, NoReturn

import typer

from ki_dev.executors.session_transcript import (
    TranscriptError,
    TranscriptRequestError,
)
from ki_dev.executors.transcript import (
    read_session_transcript,
    validate_session_request,
)
from ki_dev.session_snapshot import (
    SNAPSHOT_DIR,
    SnapshotError,
    SnapshotTitleError,
    store_snapshot,
    validate_title,
)

app = typer.Typer(
    help="Sitzungen per ID als datierten JSONL-Snapshot ablegen.",
    no_args_is_help=True,
    add_completion=False,
)

SESSION_ARG = Annotated[
    str,
    typer.Argument(metavar="SESSION_ID", help="Sitzungs-ID."),
]
AGENT_OPTION = Annotated[
    str,
    typer.Option(
        "--agent",
        metavar="AGENT",
        help="Anbieter der Sitzung (codex oder claude).",
    ),
]


@app.command("transcript")
def transcript(
    session_id: SESSION_ARG,
    agent: AGENT_OPTION,
    title: Annotated[
        str,
        typer.Option(
            "--title",
            metavar="TITEL",
            help="Titel; ergibt den Dateinamen.",
        ),
    ],
    directory: Annotated[
        Path,
        typer.Option(
            "--dir",
            metavar="ORDNER",
            help="Snapshot-Ordner.",
        ),
    ] = SNAPSHOT_DIR,
) -> None:
    """Sitzung als Snapshot ablegen (schreibt eine Datei).

    Name: YYMMDDTHH_titel_sid8.jsonl nach UTC-Sitzungsbeginn. Gleicher
    Stand wird wiederverwendet, ein neuer Stand erhält ein Suffix;
    vorhandene Dateien werden nie überschrieben. Gibt den Pfad aus.
    """
    _check_request(agent, session_id)
    _check_title(title)
    loaded = _read(agent, session_id)
    try:
        path = store_snapshot(loaded, title, directory)
    except SnapshotError as exc:
        _fail(f"Snapshot fehlgeschlagen: {exc}", code=1)
    typer.echo(path.as_posix())


def _check_request(agent: str, session_id: str) -> None:
    try:
        validate_session_request(agent, session_id)
    except TranscriptRequestError as exc:
        _fail(str(exc), code=2)


def _check_title(title: str) -> None:
    try:
        validate_title(title)
    except SnapshotTitleError as exc:
        _fail(str(exc), code=2)


def _read(agent: str, session_id: str):
    try:
        return read_session_transcript(agent, session_id)
    except TranscriptError as exc:
        details = "\n".join(f"  {problem}" for problem in exc.problems)
        _fail(f"Sitzung nicht verwendbar:\n{details}", code=1)


def _fail(message: str, *, code: int) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)
