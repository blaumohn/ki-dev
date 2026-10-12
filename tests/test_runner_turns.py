"""Übergaben aus der Deklaration (ki-dev-ablauf-qu7.2).

Der Ausführer rendert jede Übergabe aus Vorlage und Kontext des
Ablaufs; run und step nutzen dieselbe Funktion. ``runner/turns.py``
kennt keinen Ablauf.
"""

from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest

from ki_dev.adapter.contract import ReviewVocabulary, RunTask
from ki_dev.flow.model import FlowError, load_flow, parse_flow, read_raw
from ki_dev.flow.review_flow import load_review_flow
from ki_dev.ops.context.bead_input import BeadInput
from ki_dev.ops.context.blocks import TurnInput, state_turn
from ki_dev.review_context import ReviewProjection
from ki_dev.runner import implement_turns, turns
from ki_dev.runner.machine import IMPLEMENT
from ki_dev.runner.turns import Plug, bind_turns
from ki_dev.step import turn as step_turn
from ki_dev.step.choices import Step
from tests.turn_helpers import render_handoff

TURNS = Path(turns.__file__)
FLOW = load_review_flow("implement_review")
MAP = load_review_flow("map")
REVIEW_FLOWS = tuple(
    load_review_flow(name).flow
    for name in ("map", "graph", "materialize", "implement_review")
)


def _issue() -> BeadInput:
    return BeadInput(
        id="x-1",
        title="Titel",
        description="Beschreibung",
        design="Design",
        acceptance_criteria="1. a",
        source_refs=["a.md"],
    )


def _task() -> RunTask:
    return RunTask(
        "run-1",
        "Auftrag",
        (),
        Path("/w"),
        "write",
        acceptance_criteria=("K",),
    )


def _vocabulary() -> ReviewVocabulary:
    return ReviewVocabulary(
        events=("PASS", "fix"),
        texts={"fix": "korrigierbar"},
        changes="fix",
        unbound="decision",
    )


def test_run_and_step_bind_the_very_same_render_function():
    assert (
        step_turn.render_turn
        is turns.render_turn
        is implement_turns.render_turn
    )


def test_run_and_step_render_through_the_same_function(monkeypatch):
    """Eine Übergabe je Ablauf geht durch ``render_turn``."""
    seen: list[str] = []
    original = turns.render_turn

    def spy(flow, turn, subject, plug):
        seen.append(flow.name)
        return original(flow, turn, subject, plug)

    monkeypatch.setattr(turns, "render_turn", spy)
    monkeypatch.setattr(step_turn, "render_turn", spy)
    monkeypatch.setattr(implement_turns, "render_turn", spy)

    assert implement_turns.work_prompt(_task(), 1, None)
    implement_turns.review_prompt(
        _task(),
        1,
        "Bericht",
        ReviewProjection(text="Nachweis", omissions=()),
        _vocabulary(),
    )
    assert render_handoff(_issue(), Step.IMPLEMENT, flow=FLOW)
    assert seen == ["implement", "implement", "implement_review"]


def test_every_turn_operation_names_a_template():
    for flow in (*REVIEW_FLOWS, IMPLEMENT):
        names = {"turn", "ask", "work", "review"}
        for state in flow.states.values():
            for operation in state.operations:
                if operation.do in names:
                    assert operation.template, (flow.name, state.id)


def test_operation_without_template_is_rejected_at_bind():
    raw = copy.deepcopy(read_raw("implement"))
    raw["state"]["worker_step"]["operation"] = [{"do": "work"}]
    flow = parse_flow(raw)
    with pytest.raises(FlowError, match="work ohne Vorlage"):
        bind_turns(flow, implement_turns.PLUG, ("work", "review"))


def test_missing_field_is_named_extra_field_is_allowed():
    """Ein Satz Felder dient mehreren Abläufen: zusätzliche Felder
    sind erlaubt, fehlende nicht."""
    fields = dict(implement_turns.FIELDS)
    fields["orakel"] = lambda _turn: ""
    flow = load_flow("implement")
    bind_turns(flow, Plug(fields, {}), ("work", "review"))
    del fields["objection"]
    with pytest.raises(FlowError, match="Aufrufer: objection"):
        bind_turns(flow, Plug(fields, {}), ("work", "review"))


def test_foreign_block_is_named():
    blocks = {"orakel": lambda _turn: []}
    with pytest.raises(FlowError, match="nicht deklariert: orakel"):
        bind_turns(
            load_flow("implement"),
            Plug(implement_turns.FIELDS, blocks),
            ("work", "review"),
        )


def test_declared_blocks_and_fields_match_for_both_flows():
    step_turn.bind_flow(FLOW)
    bind_turns(IMPLEMENT, implement_turns.PLUG, ("work", "review"))


def test_turns_knows_no_flow():
    """Keine Zustands-, Phasen-, Ereignis- oder Vorlagennamen und
    kein Import des Planungsablaufs im Ausführer der Übergaben."""
    tree = ast.parse(TURNS.read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "ki_dev.flow.review_flow" not in imports
    assert not {
        name
        for name in imports
        if name.startswith(("ki_dev.step", "ki_dev.ops"))
    }
    names: set[str] = set()
    for flow in (*REVIEW_FLOWS, IMPLEMENT):
        names |= set(flow.states)
        names |= set(flow.vocabulary.events)
        names |= set(flow.vocabulary.operations)
        names |= {s.partition(".")[0] for s in flow.states}
        names |= {
            operation.template
            for state in flow.states.values()
            for operation in state.operations
            if operation.template
        }
        names |= {t.turn.template for t in flow.transitions if t.turn}
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef
        )
        and node.body
        and isinstance(node.body[0], ast.Expr)
    }
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    }
    assert literals & names == set()


def test_declared_edge_turn_wins_over_the_state_operation():
    """Die Kante nach einer Korrektur bestimmt die Folgenachricht."""
    edge = MAP.flow.candidates("map.correction", "done")[0]
    assert edge.turn is not None
    assert edge.turn.template == "again-map"
    assert state_turn(FLOW, "implement.review").template == (
        "review-implement"
    )


def test_blocks_render_in_declared_order_and_parts_stay_apart():
    subject = TurnInput(_issue(), FLOW, "implement")
    rendered = turns.render_turn(
        FLOW.flow,
        state_turn(FLOW, "implement"),
        subject,
        step_turn.PLUG,
    )
    names = [name for name, _ in rendered.parts]
    assert names == list(state_turn(FLOW, "implement").context)
    assert rendered.text(skip=names) == rendered.head + "\n"
