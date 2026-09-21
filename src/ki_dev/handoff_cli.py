"""Typer-Anbindung für ki-dev handoff."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ki_dev.beads_reader import (
    BeadsReadError,
    InvalidBeadIdError,
    read_issue,
)
from ki_dev.beads_source import BeadsSourceError
from ki_dev.executors.session_transcript import (
    TranscriptError,
    TranscriptRequestError,
)
from ki_dev.executors.transcript import validate_session_request
from ki_dev.handoff import HandoffInvalidError, Step, render_handoff
from ki_dev.handoff_map import map_handoff
from ki_dev.handoff_source import HandoffSourceError

HELP = """\
Zwei Formen; sie lassen sich nicht mischen.

\b
1. ki-dev handoff BEAD_ID --step STEP   (nur lesend)
2. ki-dev handoff --agent codex --session SESSION_ID   (schreibt)

Form 1 prüft einen Bead und gibt eine kopierbare Arbeitsübergabe aus.
BEAD_ID ist die Beads-ID (z. B. projekt-42). --step ist erforderlich,
es gibt keine automatische Auswahl.

\b
Schritte und Pflichtfelder (zusätzlich immer id, title, description):
  map          metadata.handoff.source_refs
  graph        metadata.handoff.source_refs
  materialize  metadata.handoff.source_refs
  build        acceptance_criteria, design
  review       acceptance_criteria, design

\b
source_refs ist eine nichtleere Liste nichtleerer Strings, z. B.
  {"handoff":{"source_refs":["docs/design/a.md#L12-L40","bd:karte"]}}
Die Referenzen werden nur als Text weitergegeben, nicht aufgelöst.

Der Befehl liest nur (bd --readonly show BEAD_ID --json), schreibt
nichts und startet keinen Agenten. Fortsetzung von Hand: Ausgabe
kopieren (oder per Umleitung speichern) und in einer passenden
getrennten Agentensitzung einfügen.

\b
Form 2 erschließt eine lokale Codex-Sitzung als Quelle für den Schritt
map. --agent und --session sind beide erforderlich; --agent bezeichnet
die Quellsitzung (nur codex), nicht den späteren Kartierungsagenten.
Es gibt keinen Dateipfad und keine automatische Wahl der letzten
Sitzung. Der Sitzungsordner kommt aus KI_DEV_CODEX_SESSIONS_DIR, sonst
CODEX_HOME/sessions, sonst ~/.codex/sessions. Der Dialog wird streng
geprüft (Benutzer/final_answer im Wechsel, ordinal eindeutig); jede
Abweichung bricht ohne Ergebnis ab, Diagnosen nennen nur Prüfcode,
Zeile und Feldpfad, nie Gesprächsinhalt. Schreibwirkung: normalisiertes
Transkript unter .local/handoff/AGENT/SESSION_ID/, dazu ein Quellen-Bead
per bd create (bei gleichem Stand wiederverwendet). stdout ist nur der
kurze map-Auftrag. Serielle Nutzung; kein Agentenstart.

\b
Exit 0: Übergabe auf stdout. Exit 2: Aufruf falsch oder Bead formal
unvollständig (Feldpfade auf stderr). Exit 1: bd nicht lesbar bzw.
Sitzung/Quelle nicht verwendbar.
"""


def handoff(
    bead_id: Annotated[
        str | None,
        typer.Argument(metavar="[BEAD_ID]", help="Beads-ID."),
    ] = None,
    step: Annotated[
        Step | None,
        typer.Option(
            "--step",
            help="map | graph | materialize | build | review",
            show_default=False,
        ),
    ] = None,
    agent: Annotated[
        str | None,
        typer.Option(
            "--agent",
            help="Anbieter der Quellsitzung (nur codex).",
            show_default=False,
        ),
    ] = None,
    session: Annotated[
        str | None,
        typer.Option(
            "--session",
            help="Sitzungs-ID der Quellsitzung.",
            show_default=False,
        ),
    ] = None,
) -> None:
    if agent is not None or session is not None:
        _map_form(bead_id, step, agent, session)
    else:
        _bead_form(bead_id, step)


def _bead_form(bead_id: str | None, step: Step | None) -> None:
    if bead_id is None or step is None:
        _fail(
            "Aufruf: BEAD_ID --step STEP oder --agent codex "
            "--session SESSION_ID",
            code=2,
        )
    try:
        issue = read_issue(bead_id, Path.cwd())
        text = render_handoff(issue, step)
    except InvalidBeadIdError as exc:
        _fail(str(exc), code=2)
    except HandoffInvalidError as exc:
        fields = "\n".join(f"  {path}" for path in exc.problems)
        _fail(
            f"Bead {bead_id} ist für Schritt {step.value} formal "
            f"unvollständig:\n{fields}",
            code=2,
        )
    except BeadsReadError as exc:
        _fail(f"Beads-Lesefehler: {exc}", code=1)
    typer.echo(text, nl=False)


def _map_form(
    bead_id: str | None,
    step: Step | None,
    agent: str | None,
    session: str | None,
) -> None:
    if bead_id is not None or step is not None:
        _fail(
            "--agent/--session lassen sich nicht mit BEAD_ID oder "
            "--step mischen",
            code=2,
        )
    if agent is None or session is None:
        _fail("--agent und --session sind beide erforderlich", code=2)
    try:
        validate_session_request(agent, session)
    except TranscriptRequestError as exc:
        _fail(str(exc), code=2)
    try:
        text = map_handoff(agent, session, Path.cwd())
    except TranscriptError as exc:
        details = "\n".join(f"  {problem}" for problem in exc.problems)
        _fail(f"Sitzung nicht verwendbar:\n{details}", code=1)
    except (
        BeadsSourceError,
        BeadsReadError,
        HandoffSourceError,
    ) as exc:
        _fail(f"Quellenübergabe fehlgeschlagen: {exc}", code=1)
    except HandoffInvalidError as exc:
        _fail(
            "Quellen-Bead formal unvollständig: "
            + ", ".join(exc.problems),
            code=1,
        )
    typer.echo(text, nl=False)


handoff.__doc__ = HELP


def _fail(message: str, *, code: int) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)
