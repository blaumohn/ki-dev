"""Übergaben für Tests: dieselbe Kette wie ``ki-dev step``, aber ohne
Ausführer-Lauf. Die Vorlage wählt der Ablauf wie am Halt: die der
Kante, die die Übergabe bestimmt, sonst die Operation des Zustands."""

from __future__ import annotations

import re
from collections.abc import Sequence

from ki_dev.flow.model import Turn
from ki_dev.flow.planning import PlanningFlow
from ki_dev.ops.checks.preflight import PreflightReport
from ki_dev.ops.context.bead_input import BeadInput
from ki_dev.ops.context.blocks import TurnInput, flow_state, state_turn
from ki_dev.ops.context.contract import ReviewTarget, Step
from ki_dev.ops.context.guidelines import GuidelineSection
from ki_dev.step.turn import hand_over, require_valid


def turn_after(flow: PlanningFlow, source: str, event: str) -> Turn:
    """Übergabe nach genau dieser Kante (ohne Wächter)."""
    edge = flow.flow.candidates(source, event)[0]
    return edge.turn or state_turn(flow, edge.target)


def render_handoff(
    issue: BeadInput,
    step: Step,
    review_target: ReviewTarget | None = None,
    guidelines: Sequence[GuidelineSection] = (),
    base_max_chars: int | None = None,
    *,
    flow: PlanningFlow,
    reading_hint: str | None = None,
    report: PreflightReport | None = None,
) -> str:
    """Erste Übergabe eines Schritts (validiert wie step)."""
    require_valid(issue, step, review_target)
    state = flow_state(step, review_target)
    subject = TurnInput(
        issue,
        flow,
        state,
        guidelines=guidelines,
        reading_hint=reading_hint,
        report=report,
    )
    return hand_over(
        flow, state_turn(flow, state), subject, base_max_chars
    )


def render_base_handoff(
    issue: BeadInput,
    step: Step,
    review_target: ReviewTarget | None = None,
    *,
    flow: PlanningFlow,
    reading_hint: str | None = None,
    max_chars: int | None = None,
) -> str:
    """Nur die Basis: ohne Leitlinien und ohne Bericht."""
    return render_handoff(
        issue,
        step,
        review_target,
        base_max_chars=max_chars,
        flow=flow,
        reading_hint=reading_hint,
    )


def render_review_handoff(
    issue: BeadInput,
    report: PreflightReport,
    guidelines: Sequence[GuidelineSection] = (),
    *,
    flow: PlanningFlow,
) -> str:
    return render_handoff(
        issue,
        Step.REVIEW,
        guidelines=guidelines,
        flow=flow,
        report=report,
    )


def render_review_turn(
    issue: BeadInput,
    target: ReviewTarget,
    report: PreflightReport | None,
    feedback: str | None,
    *,
    flow: PlanningFlow,
    pass_allowed: bool,
) -> str:
    """Folgenachricht an das Review nach einer Korrektur."""
    subject = TurnInput(
        issue,
        flow,
        f"{target.value}.review",
        report=report,
        feedback=feedback,
        pass_allowed=pass_allowed,
    )
    turn = turn_after(flow, f"{target.value}.correction", "done")
    return hand_over(flow, turn, subject)


def render_repair_turn(
    issue: BeadInput,
    finding: str,
    limit: int,
    feedback: str | None,
    *,
    flow: PlanningFlow,
) -> str:
    """Reparaturnachricht an den Umsetzer nach rotem Vorlauf."""
    subject = TurnInput(
        issue,
        flow,
        "implement.correction",
        finding=finding,
        feedback=feedback,
        feedback_limit=limit,
    )
    turn = turn_after(flow, "implement.preflight", "checks_failed")
    return hand_over(flow, turn, subject)


def without_attempt(text: str) -> str:
    """Die Versuchskennung (letzte Zeile einer Übergabe) ist je
    Aufruf neu; Vergleiche zweier Läufe lassen sie weg."""
    return re.sub(r"\nVersuch: [^\n]*\n\Z", "\n", text)


def attempt_of(text: str) -> str:
    found = re.search(r"^Versuch: (\S+)", text, re.MULTILINE)
    assert found, text
    return found.group(1)
