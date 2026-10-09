"""Typer-Anbindung für ki-dev step: Argumente, Aufrufform, Exitcodes."""

from __future__ import annotations

from typing import Annotated, NoReturn

import typer

from ki_dev.adapter.manual import TransportReadError, send
from ki_dev.ops.checks.options import PreflightOptionError
from ki_dev.ops.checks.preflight import PreflightConfigError
from ki_dev.ops.checks.stand import StandError
from ki_dev.ops.context.bead_input import BeadInputInvalidError
from ki_dev.ops.context.beads_reader import (
    BeadsReadError,
    InvalidBeadIdError,
    check_bead_id,
)
from ki_dev.ops.context.contract import ReviewTarget, Step, one_line
from ki_dev.ops.context.limit import HandoffBaseTooLongError
from ki_dev.ops.context.limit_config import (
    LimitConfigInvalidError,
    LimitConfigReadError,
)
from ki_dev.runner.planning import Halt, StaleHaltError
from ki_dev.step.boundary import CONSOLE, planning_flow
from ki_dev.step.exits import fail
from ki_dev.step.feedback import DecisionInputError, NextTurnInputError
from ki_dev.step.forms import LOCAL_WORD, MAP_WORD, local_form, map_form
from ki_dev.step.help import HELP
from ki_dev.step.options import (
    Inputs,
    PreflightValues,
    check_decision_options,
    review_options,
)
from ki_dev.step.projection import bead_output
from ki_dev.step.state import (
    SavedState,
    StepStateError,
    load_state,
    remember,
)


def handoff(
    bead_id: Annotated[
        str | None,
        typer.Argument(
            metavar="[BEAD_ID]",
            help="Beads-ID, map (Sitzungsimport) oder local "
            "(freie Sitzung ohne Bead).",
        ),
    ] = None,
    step: Annotated[
        Step | None,
        typer.Option(
            "--step",
            metavar="STEP",
            help="Schritt der Übergabe; ohne --step setzt step den "
            "gespeicherten Zustand fort.",
            show_default=False,
        ),
    ] = None,
    review_of: Annotated[
        ReviewTarget | None,
        typer.Option(
            "--review-of",
            metavar="ZIEL",
            help="map, graph, materialize oder implement (Standard); "
            "nur mit --step review.",
            show_default=False,
        ),
    ] = None,
    preflight_args: Annotated[
        list[str] | None,
        typer.Option(
            "--preflight-args",
            metavar="NAME=ARGS",
            help="ARGS an die Vorlauf-Prüfung NAME anhängen "
            "(wiederholbar; Teillauf); nur mit --step review.",
            show_default=False,
        ),
    ] = None,
    preflight_skip: Annotated[
        list[str] | None,
        typer.Option(
            "--preflight-skip",
            metavar="NAME=GRUND",
            help="Vorlauf-Prüfung NAME begründet auslassen "
            "(wiederholbar; Teillauf); nur mit --step review.",
            show_default=False,
        ),
    ] = None,
    next_turn: Annotated[
        bool,
        typer.Option(
            "--next-turn",
            help="Nächste Nachricht nach einer Korrektur (Umsetzer "
            "bei Vorlauffehler, sonst Reviewer); nur mit --step "
            "review.",
        ),
    ] = False,
    feedback_file: Annotated[
        str | None,
        typer.Option(
            "--feedback-file",
            metavar="DATEI|-",
            help="Rückmeldung des Schreibagenten (UTF-8; - liest "
            "stdin); nur mit --next-turn.",
            show_default=False,
        ),
    ] = None,
    decision_file: Annotated[
        str | None,
        typer.Option(
            "--decision-file",
            metavar="DATEI|-",
            help="JSON-Antwort der Umsetzungs-Review (- liest stdin); "
            "nur mit --next-turn, ohne Vorlauf.",
            show_default=False,
        ),
    ] = None,
    agent: Annotated[
        str | None,
        typer.Option(
            "--agent",
            metavar="AGENT",
            help="Anbieter der Quellsitzung (codex oder claude).",
            show_default=False,
        ),
    ] = None,
    session: Annotated[
        str | None,
        typer.Option(
            "--session",
            metavar="SESSION_ID",
            help="Sitzungs-ID der Quellsitzung.",
            show_default=False,
        ),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option(
            "--title",
            metavar="TITEL",
            help="Titel des Snapshots (nur mit map --agent/--session).",
            show_default=False,
        ),
    ] = None,
) -> None:
    options = PreflightValues(
        preflight_args or [], preflight_skip or []
    )
    if bead_id == LOCAL_WORD:
        local_form(
            step,
            review_of,
            options,
            next_turn
            or feedback_file is not None
            or decision_file is not None,
            agent,
            session,
            title,
        )
    elif (
        agent is not None or session is not None or bead_id == MAP_WORD
    ):
        map_form(
            bead_id,
            step,
            review_of,
            options,
            next_turn
            or feedback_file is not None
            or decision_file is not None,
            agent,
            session,
            title,
        )
    else:
        if title is not None:
            fail("--title gilt nur für map --agent/--session", code=2)
        _bead_form(
            bead_id,
            step,
            review_of,
            options,
            next_turn,
            Inputs(feedback_file, decision_file),
        )

def _bead_form(
    bead_id: str | None,
    step: Step | None,
    review_of: ReviewTarget | None,
    options: PreflightValues,
    next_turn: bool,
    inputs: Inputs,
) -> None:
    if bead_id is None:
        fail(
            "Aufruf: BEAD_ID [--step STEP] oder map --agent codex "
            "--session SESSION_ID",
            code=2,
        )
    saved = _saved_state(bead_id, explicit=step is not None)
    if step is None:
        _continue(bead_id, saved, review_of, options, next_turn, inputs)
        return
    extra = review_options(
        step, review_of, options, next_turn, inputs.feedback
    )
    check_decision_options(review_of, options, next_turn, inputs)
    try:
        output = bead_output(
            bead_id, step, review_of, extra, next_turn, inputs, saved
        )
    except (
        InvalidBeadIdError,
        NextTurnInputError,
        DecisionInputError,
        LimitConfigInvalidError,
        HandoffBaseTooLongError,
    ) as exc:
        fail(str(exc), code=2)
    except StandError as exc:
        fail(f"Stand nicht ermittelbar: {exc}", code=1)
    except BeadInputInvalidError as exc:
        _fail_incomplete(bead_id, step, exc)
    except BeadsReadError as exc:
        fail(f"Beads-Lesefehler: {exc}", code=1)
    except PreflightOptionError as exc:
        fail(f"Aufruf ungültig: {exc}", code=2)
    except PreflightConfigError as exc:
        fail(f"Vorlauf-Konfiguration ungültig: {exc}", code=2)
    except (TransportReadError, LimitConfigReadError) as exc:
        fail(str(exc), code=1)
    _note_jump(saved, output.halt)
    remember(
        bead_id,
        output.halt,
        output.flow.flow,
        None if saved is None else saved.state,
    )
    send(CONSOLE, output.halt.attempt or "", output.text)
    if output.exit_code:
        raise typer.Exit(code=output.exit_code)

def _saved_state(bead_id: str, *, explicit: bool) -> SavedState | None:
    """Gespeicherter Halt; ein Halt aus einem anderen Ablaufstand lässt
    sich nicht fortsetzen, ein ausdrückliches --step beginnt neu."""
    try:
        check_bead_id(bead_id)
        return load_state(bead_id)
    except StaleHaltError as exc:
        if explicit:
            return None
        fail(f"Bead {bead_id}: {exc}", code=2)
    except InvalidBeadIdError as exc:
        fail(str(exc), code=2)
    except StepStateError as exc:
        fail(f"Laufzustand ungültig: {exc}", code=2)

def _continue(
    bead_id: str,
    saved: SavedState | None,
    review_of: ReviewTarget | None,
    options: PreflightValues,
    next_turn: bool,
    inputs: Inputs,
) -> None:
    """Ohne --step: den gespeicherten Zustand fortsetzen. Nach dem
    Schreiben folgt das Review, nach der Korrektur die Folgerunde; wo
    eine Antwort oder Entscheidung fehlt, nennt step die
    Folgeschritte."""
    if review_of or options or next_turn or any(inputs):
        fail(
            "ohne --step setzt step den gespeicherten Zustand fort; "
            "weitere Optionen nur mit --step",
            code=2,
        )
    if saved is None:
        fail(
            f"Bead {bead_id}: kein gespeicherter Zustand; beginne mit "
            "--step STEP",
            code=2,
        )
    flow = planning_flow()
    kind = flow.flow.state(saved.state).kind
    phase = saved.state.partition(".")[0]
    if kind in ("write", "correction"):
        _bead_form(
            bead_id,
            Step.REVIEW,
            ReviewTarget(phase),
            PreflightValues([], []),
            kind == "correction",
            Inputs(None, None),
        )
        return
    lines = flow.hint_lines(saved.state, one_line(bead_id))
    typer.echo("\n".join(lines) + "\n", nl=False)

def _note_jump(saved: SavedState | None, halt: Halt) -> None:
    """Beginnt ein Aufruf woanders, als der letzte endete, steht das im
    Protokoll (check_conformance) und hier als Hinweis auf stderr."""
    start = halt.entry.source if halt.entry is not None else halt.state
    if saved is not None and saved.state != start:
        typer.echo(
            f"Hinweis: letzter Halt {saved.state}, dieser Aufruf "
            f"beginnt in {start} (im Protokoll als Sprung sichtbar).",
            err=True,
        )

def _fail_incomplete(
    bead_id: str, step: Step, error: BeadInputInvalidError
) -> NoReturn:
    fields = "\n".join(f"  {path}" for path in error.problems)
    fail(
        f"Bead {bead_id} ist für Schritt {step.value} formal "
        f"unvollständig:\n{fields}",
        code=2,
    )

handoff.__doc__ = HELP
