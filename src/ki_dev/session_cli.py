"""Kommandozeile ``ki-dev session``: auflisten, ablegen, anzeigen,
exportieren.

Auswahl per expliziter ID und Anbieter, Nummer der Liste (``-n``)
oder ausdruecklichem Snapshot; Suche und Katalog gehoeren zu 70u.3.
Nur ``transcript``
schreibt ins Archiv. Diagnosen gehen ausschliesslich nach stderr und
nennen nie Inhalte.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from ki_dev.adapter.executors.session_transcript import (
    SessionTranscript,
    TranscriptError,
    TranscriptRequestError,
)
from ki_dev.adapter.executors.transcript import (
    read_session_transcript,
    validate_session_request,
)
from ki_dev.session_list import NR_OPTION, list_sessions, pick_ref
from ki_dev.session_output import (
    OutputExistsError,
    fail,
    print_rich,
    write_bytes,
)
from ki_dev.session_snapshot import (
    SNAPSHOT_DIR,
    SnapshotError,
    SnapshotTitleError,
    read_snapshot,
    serialize_snapshot,
    store_snapshot,
    validate_title,
)
from ki_dev.session_view import (
    transcript_markdown,
    transcript_renderable,
)


class ExportFormat(StrEnum):
    MARKDOWN = "markdown"
    JSONL = "jsonl"


app = typer.Typer(
    help="Sitzungen auflisten, ablegen, anzeigen oder exportieren.",
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
OPTIONAL_SESSION_ARG = Annotated[
    str | None,
    typer.Argument(
        metavar="[SESSION_ID]",
        help="Sitzungs-ID (mit --agent).",
        show_default=False,
    ),
]
OPTIONAL_AGENT_OPTION = Annotated[
    str | None,
    typer.Option(
        "--agent",
        metavar="AGENT",
        help="Anbieter der Sitzung (codex oder claude).",
        show_default=False,
    ),
]
SNAPSHOT_OPTION = Annotated[
    Path | None,
    typer.Option(
        "--snapshot",
        metavar="DATEI",
        help="Gespeicherten Snapshot statt Rohsitzung lesen.",
        show_default=False,
    ),
]


app.command("list")(list_sessions)


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
        fail(f"Snapshot fehlgeschlagen: {exc}", code=1)
    typer.echo(path.as_posix())


def _check_request(agent: str, session_id: str) -> None:
    try:
        validate_session_request(agent, session_id)
    except TranscriptRequestError as exc:
        fail(str(exc), code=2)


def _check_title(title: str) -> None:
    try:
        validate_title(title)
    except SnapshotTitleError as exc:
        fail(str(exc), code=2)


def _read(agent: str, session_id: str):
    try:
        return read_session_transcript(agent, session_id)
    except TranscriptError as exc:
        details = "\n".join(f"  {problem}" for problem in exc.problems)
        fail(f"Sitzung nicht verwendbar:\n{details}", code=1)


@app.command("show")
def show(
    session_id: OPTIONAL_SESSION_ARG = None,
    agent: OPTIONAL_AGENT_OPTION = None,
    snapshot: SNAPSHOT_OPTION = None,
    nr: NR_OPTION = None,
    pager: Annotated[
        bool,
        typer.Option(
            "--pager",
            help="Am Terminal im Pager von Rich anzeigen.",
        ),
    ] = False,
) -> None:
    """Sitzung lesbar anzeigen (schreibt nichts).

    Titel, Anbieter/Sitzung und Zeit einmal, danach Rollen und
    Markdown-Beiträge. Umgeleitete Ausgabe ist ungekürzt und ohne
    Farbcodes; --pager wirkt nur am Terminal.
    """
    loaded, title = _select(session_id, agent, snapshot, nr)
    print_rich(transcript_renderable(loaded, title), pager=pager)


@app.command("export")
def export(
    output_format: Annotated[
        ExportFormat,
        typer.Option("--format", help="Ausgabeformat."),
    ],
    session_id: OPTIONAL_SESSION_ARG = None,
    agent: OPTIONAL_AGENT_OPTION = None,
    snapshot: SNAPSHOT_OPTION = None,
    nr: NR_OPTION = None,
    title: Annotated[
        str | None,
        typer.Option(
            "--title",
            metavar="TITEL",
            help="Titel (für jsonl ohne gespeicherten Titel Pflicht).",
            show_default=False,
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            metavar="DATEI",
            help="Neue Datei statt stdout (nie überschrieben).",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Sitzung als Markdown oder JSONL ausgeben (ohne Archiv).

    JSONL folgt dem Snapshot-Vertrag (Kopf, dann Nachrichten); Markdown
    enthält denselben Transkriptinhalt. Diagnosen nur auf stderr.
    """
    if title is not None:
        _check_title(title)
    loaded, stored_title = _select(session_id, agent, snapshot, nr)
    chosen = title or stored_title
    if output_format is ExportFormat.JSONL:
        if chosen is None:
            fail(
                "--title ist für jsonl erforderlich (Kopfzeile)", code=2
            )
        data = _serialized(loaded, chosen)
    else:
        data = transcript_markdown(loaded, chosen).encode("utf-8")
    try:
        write_bytes(data, output)
    except OutputExistsError as exc:
        fail(str(exc), code=1)
    except OSError as exc:
        fail(
            f"Ausgabe nicht schreibbar ({type(exc).__name__})", code=1
        )


def _select(
    session_id: str | None,
    agent: str | None,
    snapshot: Path | None,
    nr: int | None,
) -> tuple[SessionTranscript, str | None]:
    """Genau eine Auswahl: ID mit Anbieter, Nummer oder Snapshot."""
    if nr is not None:
        if session_id is not None or snapshot is not None:
            fail(
                "-n nicht mit SESSION_ID/--snapshot mischen", code=2
            )
        ref = pick_ref(agent, nr)
        return _read(ref.agent, ref.session_id), None
    if snapshot is not None:
        if session_id is not None or agent is not None:
            fail(
                "--snapshot nicht mit SESSION_ID/--agent mischen",
                code=2,
            )
        try:
            stored = read_snapshot(snapshot)
        except SnapshotError as exc:
            fail(f"Snapshot nicht verwendbar: {exc}", code=1)
        return stored.transcript, stored.title
    if session_id is None or agent is None:
        fail(
            "SESSION_ID mit --agent, -n NR oder --snapshot DATEI "
            "angeben",
            code=2,
        )
    _check_request(agent, session_id)
    return _read(agent, session_id), None


def _serialized(loaded: SessionTranscript, title: str) -> bytes:
    try:
        return serialize_snapshot(loaded, title)
    except SnapshotError as exc:
        fail(f"Export fehlgeschlagen: {exc}", code=1)
