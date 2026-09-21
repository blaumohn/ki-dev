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
from ki_dev.handoff import HandoffInvalidError, Step, render_handoff

HELP = """\
Prüft einen Bead und gibt eine kopierbare Arbeitsübergabe aus.

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
Exit 0: Übergabe auf stdout. Exit 2: Aufruf falsch oder Bead formal
unvollständig (Feldpfade auf stderr). Exit 1: bd nicht lesbar.
"""


def handoff(
    bead_id: Annotated[
        str, typer.Argument(metavar="BEAD_ID", help="Beads-ID.")
    ],
    step: Annotated[
        Step,
        typer.Option(
            "--step",
            help="map | graph | materialize | build | review",
            show_default=False,
        ),
    ],
) -> None:
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


handoff.__doc__ = HELP


def _fail(message: str, *, code: int) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)
