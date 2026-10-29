"""``ki-dev session list`` und die Auswahl per Nummer (``-n``).

Die Nummer gilt für die Liste des Aufrufs: ``show -n 3`` wählt den
dritten Eintrag von ``list`` zum selben Zeitpunkt. Neue Sitzungen
verschieben sie; die Liste zeigt deshalb auch die Sitzungs-ID.
"""

from __future__ import annotations

from functools import partial
from typing import Annotated

import typer

from ki_dev.adapter.executors.session_catalog import (
    SessionListing,
    SessionRef,
    recent_sessions,
)
from ki_dev.adapter.executors.session_config import read_session_config
from ki_dev.adapter.executors.session_transcript import (
    TranscriptError,
    TranscriptRequestError,
)
from ki_dev.adapter.executors.transcript import (
    read_session_transcript,
    transcript_agents,
    validate_agent,
)
from ki_dev.session_filter import is_automatic_session
from ki_dev.session_output import fail, print_rich
from ki_dev.session_view import ListEntry, listing_renderable

DEFAULT_COUNT = 10

COUNT_ARG = Annotated[
    int,
    typer.Argument(
        metavar="[ANZAHL]",
        min=1,
        help="Anzahl der neuesten Sitzungen.",
    ),
]
LIST_AGENT_OPTION = Annotated[
    str | None,
    typer.Option(
        "--agent",
        metavar="AGENT",
        help="Nur diesen Anbieter (codex oder claude); sonst alle.",
        show_default=False,
    ),
]
NR_OPTION = Annotated[
    int | None,
    typer.Option(
        "-n",
        "--nr",
        metavar="NR",
        min=1,
        help="Sitzung Nr. aus `session list` (gleiche Filter).",
        show_default=False,
    ),
]
INCLUDE_TESTS_OPTION = Annotated[
    bool,
    typer.Option(
        "--include-tests",
        help="Auch Bau-/Review-, Test- und Subagentensitzungen.",
    ),
]


def list_sessions(
    count: COUNT_ARG = DEFAULT_COUNT,
    agent: LIST_AGENT_OPTION = None,
    include_tests: INCLUDE_TESTS_OPTION = False,
) -> None:
    """Neueste Sitzungen nummeriert mit Kurzvorschau (schreibt nichts).

    Alle Anbieter zusammen, neueste Datei zuerst. Je Sitzung: Nummer,
    Anbieter, letzte Aktivität, ID sowie Beginn des ersten Mensch- und
    Agent-Beitrags. Auswahl: `session show -n NR` oder `export -n NR`.
    Quellen: Umgebungsvariablen, dann tool.ki-dev.session in
    pyproject.toml,
    sonst ~/.codex/sessions beziehungsweise ~/.claude/projects.
    Automatische Sitzungen werden vor der Anzahlbegrenzung ausgeblendet.
    """
    listing = select_listing(agent, count, include_tests)
    if not listing.refs:
        typer.echo("Keine Sitzungen gefunden.", err=True)
        return
    entries = [_entry(ref) for ref in listing.refs]
    print_rich(listing_renderable(entries), pager=False)


def pick_ref(
    agent: str | None, number: int, include_tests: bool = False
) -> SessionRef:
    """Eintrag ``number`` der Liste; zu große Nummer ist ein Fehler."""
    listing = select_listing(agent, number, include_tests)
    if len(listing.refs) < number:
        fail(
            f"Nummer {number} nicht vorhanden "
            f"({len(listing.refs)} Sitzungen)",
            code=1,
        )
    return listing.refs[number - 1]


def select_listing(
    agent: str | None, limit: int | None, include_tests: bool = False
) -> SessionListing:
    agents = (agent,) if agent is not None else transcript_agents()
    try:
        if agent is not None:
            validate_agent(agent)
        config = read_session_config()
        exclude = (
            None
            if include_tests
            else partial(
                is_automatic_session,
                exclude_cwd=config.get("exclude_cwd", ()),
            )
        )
        listing = recent_sessions(
            agents, limit, exclude=exclude, config=config
        )
    except TranscriptRequestError as exc:
        fail(str(exc), code=2)
    except TranscriptError as exc:
        details = "\n".join(f"  {problem}" for problem in exc.problems)
        fail(f"Sitzungen nicht auflistbar:\n{details}", code=1)
    except ValueError as exc:
        fail(str(exc), code=1)
    if agent is not None and listing.missing:
        fail(f"Sitzungsordner für {agent} fehlt", code=1)
    for name in listing.missing:
        typer.echo(f"Hinweis: kein Sitzungsordner für {name}", err=True)
    return listing


def _entry(ref: SessionRef) -> ListEntry:
    try:
        transcript = read_session_transcript(ref.agent, ref.session_id)
    except TranscriptError as exc:
        return ListEntry(ref, None, exc.problems)
    return ListEntry(ref, transcript)
