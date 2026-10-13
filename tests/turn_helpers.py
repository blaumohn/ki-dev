"""Übergaben für Tests: dieselbe Kette wie ``ki-dev step``, aber ohne
Ausführer-Lauf. Die Vorlage wählt der Ablauf wie am Halt: die der
Kante, die die Übergabe bestimmt, sonst die Operation des Zustands."""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from pathlib import Path

from typer.testing import CliRunner, Result

from ki_dev.flow.model import Turn, load_flow_file
from ki_dev.flow.package import find_flow
from ki_dev.flow.review_flow import (
    ReviewFlow,
    load_review_flow,
    review_flow_files,
)
from ki_dev.ops.checks.preflight import PreflightReport
from ki_dev.ops.context.bead_input import BeadInput, validate_bead_input
from ki_dev.ops.context.blocks import TurnInput, state_turn
from ki_dev.ops.context.guidelines import (
    GuidelineDocument,
    GuidelineSection,
    select_guidelines,
)
from ki_dev.step.cli import step_app
from ki_dev.step.turn import hand_over, require_valid

WRITE_STATES = ("map", "graph", "materialize", "implement")
"""Schreibübergaben der mitgelieferten Review-Abläufe (Phase)."""

REVIEW_STATES = tuple(f"{phase}.review" for phase in WRITE_STATES)

HANDOFF_STATES = WRITE_STATES + REVIEW_STATES


def flow_name(state: str) -> str:
    """Der Ablauf, zu dem ein Zustand gehört (``map.review`` →
    ``map``, ``implement`` → ``implement_review``)."""
    return review_flow_files()[state.partition(".")[0]]


def phase_flow(state: str) -> ReviewFlow:
    """Der mitgelieferte Ablauf eines Zustands."""
    return load_review_flow(flow_name(state))


def validate_for(issue: BeadInput, state: str) -> tuple[str, ...]:
    """Formale Prüfung wie step: ``require`` und Baustein ``criteria``
    der Übergabe aus dem mitgelieferten Ablauf."""
    (operation,) = phase_flow(state).flow.state(state).operations
    return validate_bead_input(
        issue,
        operation.require,
        criteria="criteria" in operation.context,
    )


def select_for(
    documents: Sequence[GuidelineDocument], state: str
) -> tuple[GuidelineSection, ...]:
    """Leitlinienwahl wie step: Phase des Ablaufs, Review oder nicht."""
    return select_guidelines(
        tuple(documents),
        phase_flow(state).flow.start,
        state in REVIEW_STATES,
    )


def turn_after(flow: ReviewFlow, source: str, event: str) -> Turn:
    """Übergabe nach genau dieser Kante (ohne Wächter)."""
    edge = flow.flow.candidates(source, event)[0]
    return edge.turn or state_turn(flow.flow, edge.target)


def render_handoff(
    issue: BeadInput,
    state: str,
    guidelines: Sequence[GuidelineSection] = (),
    base_max_chars: int | None = None,
    *,
    flow: ReviewFlow | None = None,
    reading_hint: str | None = None,
    report: PreflightReport | None = None,
) -> str:
    """Übergabe des Zustands (validiert wie step); ohne ``flow`` der
    mitgelieferte Ablauf des Zustands."""
    flow = flow or phase_flow(state)
    require_valid(issue, flow.flow, state)
    subject = TurnInput(
        issue,
        flow.flow,
        state,
        guidelines=guidelines,
        reading_hint=reading_hint,
        report=report,
    )
    return hand_over(
        flow.flow, state_turn(flow.flow, state), subject, base_max_chars
    )


def render_base_handoff(
    issue: BeadInput,
    state: str,
    *,
    reading_hint: str | None = None,
    max_chars: int | None = None,
) -> str:
    """Nur die Basis: ohne Leitlinien und ohne Bericht."""
    return render_handoff(
        issue,
        state,
        base_max_chars=max_chars,
        reading_hint=reading_hint,
    )


def render_review_handoff(
    issue: BeadInput,
    report: PreflightReport,
    guidelines: Sequence[GuidelineSection] = (),
) -> str:
    return render_handoff(
        issue,
        "implement.review",
        guidelines=guidelines,
        report=report,
    )


def render_review_turn(
    issue: BeadInput,
    phase: str,
    report: PreflightReport | None,
    feedback: str | None,
    *,
    pass_allowed: bool,
) -> str:
    """Folgenachricht an das Review nach einer Korrektur."""
    flow = phase_flow(phase)
    subject = TurnInput(
        issue,
        flow.flow,
        f"{phase}.review",
        report=report,
        feedback=feedback,
        pass_allowed=pass_allowed,
    )
    turn = turn_after(flow, f"{phase}.correction", "done")
    return hand_over(flow.flow, turn, subject)


def render_repair_turn(
    issue: BeadInput,
    finding: str,
    limit: int,
    feedback: str | None,
) -> str:
    """Reparaturnachricht an den Umsetzer nach rotem Vorlauf."""
    flow = load_review_flow("implement_review")
    subject = TurnInput(
        issue,
        flow.flow,
        "implement.correction",
        finding=finding,
        feedback=feedback,
        feedback_limit=limit,
    )
    turn = turn_after(flow, "implement.preflight", "checks_failed")
    return hand_over(flow.flow, turn, subject)


def flow_step(name: str, *args: str, **kwargs) -> Result:
    """``ki-dev -f NAME step ARGS`` über den Befehl des Gerüsts, wie
    ``ki-dev -f`` ihn baut (ohne die Zeile ``Ablauf: …`` auf
    stderr)."""
    path = find_flow(name, Path.cwd(), os.environ)
    app = step_app(load_flow_file(path), path)
    return CliRunner().invoke(app, list(args), **kwargs)


def handoff_of(
    state: str, *options: str, bead: str = "x-1", **kwargs
) -> Result:
    """Übergabe eines Zustands ohne Antwort."""
    return flow_step(flow_name(state), bead, state, *options, **kwargs)


def write_done(
    phase: str, *options: str, bead: str = "x-1", **kwargs
) -> Result:
    """Schreiben erledigt (Antwort ``{}``): der Ablauf geht ins
    Review, bei implement über den Vorlauf."""
    return _answered(phase, "{}", options, bead, kwargs)


def correction_done(
    phase: str,
    *options: str,
    feedback: str | None = None,
    bead: str = "x-1",
    **kwargs,
) -> Result:
    """Korrektur erledigt, wahlweise mit Rückmeldung des
    Schreibagenten."""
    answer = (
        "{}" if feedback is None else json.dumps({"feedback": feedback})
    )
    state = f"{phase}.correction"
    return _answered(state, answer, options, bead, kwargs)


def review_answer(
    phase: str, source: str, *more: str, bead: str = "x-1", **kwargs
) -> Result:
    """Antwort des Reviews aus ``source`` (Datei oder ``-``); ``more``
    sind weitere Antworten oder Optionen."""
    state = f"{phase}.review"
    answer = f"{state}={source}"
    return flow_step(
        flow_name(state), bead, state, answer, *more, **kwargs
    )


def _answered(state, answer, options, bead, kwargs) -> Result:
    return flow_step(
        flow_name(state),
        bead,
        state,
        f"{state}=-",
        *options,
        input=answer,
        **kwargs,
    )
