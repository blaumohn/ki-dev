"""Die Formen ``local`` und ``map`` (Sitzungsimport) von ``step``."""

from __future__ import annotations

from pathlib import Path

import typer

from ki_dev.adapter.executors.session_transcript import (
    TranscriptError,
    TranscriptRequestError,
)
from ki_dev.adapter.executors.transcript import validate_session_request
from ki_dev.ops.context.bead_input import BeadInputInvalidError
from ki_dev.ops.context.beads_reader import BeadsReadError
from ki_dev.ops.context.guidelines import select_common_guidelines
from ki_dev.ops.context.limit import HandoffBaseTooLongError
from ki_dev.session_snapshot import SnapshotTitleError, validate_title
from ki_dev.step.beads_source import BeadsSourceError
from ki_dev.step.boundary import (
    base_limit,
    bound_flow,
    guideline_documents,
    selected_guidelines,
)
from ki_dev.step.exits import fail
from ki_dev.step.local import render_local_handoff
from ki_dev.step.map import map_handoff
from ki_dev.step.source import HandoffSourceError

MAP_WORD = "map"

LOCAL_WORD = "local"

MAP_KEPT_NOTE = (
    "Quelle und Quellen-Bead bleiben bestehen und werden bei "
    "erneutem Aufruf wiederverwendet."
)

def local_form(
    agent: str | None, session: str | None, title: str | None
) -> None:
    """``local``: weder Bead noch ``bd``; Konfiguration und Quellen
    werden gelesen, sonst nichts (keine Schreibwirkung)."""
    if agent is not None or session is not None or title is not None:
        fail(
            "local lässt sich nicht mit --agent/--session/--title "
            "mischen",
            code=2,
        )
    limit = base_limit()
    guidelines = select_common_guidelines(guideline_documents())
    try:
        text = render_local_handoff(guidelines, limit)
    except HandoffBaseTooLongError as exc:
        fail(str(exc), code=2)
    typer.echo(text, nl=False)

def map_form(
    form: str | None,
    agent: str | None,
    session: str | None,
    title: str | None,
) -> None:
    if form != MAP_WORD:
        fail(
            "Sitzungsform: ki-dev step map --agent codex --session "
            "SESSION_ID --title TITEL",
            code=2,
        )
    if agent is None or session is None:
        fail("--agent und --session sind beide erforderlich", code=2)
    if title is None:
        fail(
            "--title ist für den Sitzungsimport erforderlich "
            "(Snapshot-Name)",
            code=2,
        )
    try:
        validate_session_request(agent, session)
        validate_title(title)
    except (TranscriptRequestError, SnapshotTitleError) as exc:
        fail(str(exc), code=2)
    typer.echo(map_text(agent, session, title), nl=False)

def map_text(agent: str, session: str, title: str) -> str:
    """Sitzungsimport mit Konfigurations- und Leitlinienprüfung vor
    jeder Schreibwirkung."""
    limit = base_limit()
    flow, _ = bound_flow(MAP_WORD)
    guidelines = selected_guidelines(flow, review=False)
    try:
        text = map_handoff(
            agent, session, title, Path.cwd(), guidelines, limit, flow
        )
    except HandoffBaseTooLongError as exc:
        fail(exc.diagnosis(MAP_KEPT_NOTE), code=2)
    except TranscriptError as exc:
        details = "\n".join(f"  {problem}" for problem in exc.problems)
        fail(f"Sitzung nicht verwendbar:\n{details}", code=1)
    except (
        BeadsSourceError,
        BeadsReadError,
        HandoffSourceError,
    ) as exc:
        fail(f"Quellenübergabe fehlgeschlagen: {exc}", code=1)
    except BeadInputInvalidError as exc:
        fail(
            "Quellen-Bead formal unvollständig: "
            + ", ".join(exc.problems),
            code=1,
        )
    return text
