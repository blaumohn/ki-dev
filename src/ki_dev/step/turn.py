"""Übergabe an den Menschen als Boten: der Ausführer rendert, step
steckt Felder und Bausteine der step-Abläufe ein (``ops.context``)
und prüft die Basisgrenze."""

from __future__ import annotations

from ki_dev.flow.model import Flow, FlowError, Operation, Turn
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
)
from ki_dev.ops.context.limit import check_base_length
from ki_dev.runner.turns import Plug, bind_turns, render_turn

PLUG = Plug(FIELDS, BLOCKS)


def bind_flow(flow: Flow) -> None:
    """Ablauf und eingesteckte Felder und Bausteine passen; Übergaben
    sind wie beim Ausführer die Operationen ohne Bindung."""
    used = {
        operation.do
        for state in flow.states.values()
        for operation in state.operations
    }
    bind_turns(flow, PLUG, used - set(flow.bindings))


def require_valid(
    issue: BeadInput, flow: Flow, state: str
) -> None:
    """Formal unvollständige Beads lehnt jede erste Übergabe ab: der
    Ablauf nennt am Zustand die Bead-Felder (``require``), der
    Baustein ``criteria`` verlangt zerlegbare Abnahmekriterien."""
    operation = _turn_operation(flow, state)
    problems = validate_bead_input(
        issue,
        operation.require,
        criteria="criteria" in operation.context,
    )
    if problems:
        raise BeadInputInvalidError(problems)


def hand_over(
    flow: Flow,
    turn: Turn | None,
    subject: TurnInput,
    base_max_chars: int | None = None,
) -> str:
    """Übergabe aus ihrer Deklaration; die Grenze gilt nur für die
    Basis (``None``: ungeprüft), nie für Bericht und Leitlinien."""
    if turn is None:
        raise FlowError(
            f"{flow.name}.toml: der Halt bestimmt keine Übergabe"
        )
    rendered = render_turn(flow, turn, subject, PLUG)
    if base_max_chars is not None:
        check_base_length(
            rendered.text(OUTSIDE_BASE),
            base_max_chars,
            base_fields(subject, turn.context),
        )
    return rendered.text()


def _turn_operation(flow: Flow, state: str) -> Operation:
    """Die Operation des Zustands, die seine Übergabe trägt."""
    for operation in flow.state(state).operations:
        if operation.turn is not None:
            return operation
    raise FlowError(
        f"{flow.name}.toml: {state} hat keine Übergabevorlage"
    )
