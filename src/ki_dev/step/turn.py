"""Übergabe an den Menschen als Boten: der Ausführer rendert, step
steckt Felder und Bausteine der step-Abläufe ein (``ops.context``)
und prüft die Basisgrenze."""

from __future__ import annotations

from ki_dev.flow.model import FlowError, Turn
from ki_dev.flow.review_flow import ReviewFlow
from ki_dev.ops.context.bead_input import (
    BeadInput,
    BeadInputInvalidError,
    validate_bead_input,
)
from ki_dev.ops.context.blocks import (
    BLOCKS,
    FIELDS,
    OUTSIDE_BASE,
    TurnInput,
    base_fields,
    state_turn,
)
from ki_dev.ops.context.contract import ReviewTarget, Step
from ki_dev.ops.context.limit import check_base_length
from ki_dev.runner.planning import ASK, TURN
from ki_dev.runner.turns import Plug, bind_turns, render_turn

PLUG = Plug(FIELDS, BLOCKS)


def bind_flow(flow: ReviewFlow) -> None:
    """Ablauf und eingesteckte Felder und Bausteine passen."""
    bind_turns(flow.flow, PLUG, (TURN, ASK))


def require_valid(
    issue: BeadInput, step: Step, review_target: ReviewTarget | None
) -> None:
    """Formal unvollständige Beads lehnt jede erste Übergabe ab."""
    problems = validate_bead_input(issue, step, review_target)
    if problems:
        raise BeadInputInvalidError(problems)


def hand_over(
    flow: ReviewFlow,
    turn: Turn | None,
    subject: TurnInput,
    base_max_chars: int | None = None,
) -> str:
    """Übergabe aus ihrer Deklaration; die Grenze gilt nur für die
    Basis (``None``: ungeprüft), nie für Bericht und Leitlinien."""
    if turn is None:
        raise FlowError(
            f"{flow.file}: der Halt bestimmt keine Übergabe"
        )
    rendered = render_turn(flow.flow, turn, subject, PLUG)
    if base_max_chars is not None:
        check_base_length(
            rendered.text(OUTSIDE_BASE),
            base_max_chars,
            base_fields(subject, turn.context),
        )
    return rendered.text()


def ensure_base_fits(
    flow: ReviewFlow,
    issue: BeadInput,
    step: Step,
    review_target: ReviewTarget | None,
    state: str,
    base_max_chars: int,
) -> None:
    """Basisgrenze der Übergabe in ``state`` prüfen, ohne den Text zu
    verwenden (vor einem Vorlauf, der Dateien ändern kann)."""
    require_valid(issue, step, review_target)
    hand_over(
        flow,
        state_turn(flow, state),
        TurnInput(issue, flow, state),
        base_max_chars,
    )
