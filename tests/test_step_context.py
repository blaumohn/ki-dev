"""Kontext der Übergabe als Ablaufdaten (ki-dev-ablauf-twa).

planning.toml deklariert je Übergabezustand Rollenvorlage und
Kontextbausteine; step setzt die Bausteine unter ihrem Namen um.
"""

from __future__ import annotations

import copy

import pytest

from ki_dev.flow.model import FlowError, parse_flow, read_raw
from ki_dev.flow.planning import PlanningFlow, load_planning_flow
from ki_dev.ops.context import bead_input
from ki_dev.ops.context.blocks import BLOCKS, flow_state, state_turn
from ki_dev.ops.context.contract import ReviewTarget, Step
from ki_dev.step.turn import bind_flow
from tests.turn_helpers import render_handoff

FLOW = load_planning_flow()

FORMS = [
    *((step, None) for step in Step if step is not Step.REVIEW),
    *((Step.REVIEW, target) for target in ReviewTarget),
]


def test_caller_implements_exactly_the_declared_context():
    bind_flow(FLOW)
    assert set(BLOCKS) == set(FLOW.flow.vocabulary.context)


def test_missing_block_is_named(monkeypatch):
    monkeypatch.delitem(BLOCKS, "criteria")
    with pytest.raises(FlowError, match="fehlt: criteria"):
        bind_flow(FLOW)


def test_unknown_context_name_is_rejected_at_load():
    raw = copy.deepcopy(read_raw("planning"))
    raw["phase"][0]["context"]["write"].append({"use": "orakel"})
    with pytest.raises(FlowError, match="unbekannte Kontextbausteine"):
        parse_flow(raw)


def test_missing_template_file_is_rejected_at_load():
    raw = copy.deepcopy(read_raw("planning"))
    raw["phase"][0]["template"]["write"] = "role-fehlt"
    with pytest.raises(FlowError, match="role-fehlt.txt fehlt"):
        parse_flow(raw)


def test_context_on_unknown_local_state_is_rejected():
    raw = copy.deepcopy(read_raw("planning"))
    raw["phase"][0]["context"]["nirgends"] = [{"use": "criteria"}]
    with pytest.raises(FlowError, match="context.nirgends: unbekannt"):
        parse_flow(raw)


@pytest.mark.parametrize(
    ("step", "target"), FORMS, ids=[f"{s.value}-{t}" for s, t in FORMS]
)
def test_validation_rules_match_the_declared_context(step, target):
    """Pflichtfeld-Verträge der Validierung und deklarierter Kontext
    sind dieselbe Aussage: ein Test hält sie deckungsgleich."""
    context = state_turn(FLOW, flow_state(step, target)).context
    refs = "source_refs" in context
    assert bead_input._needs_refs(step, target) is refs
    assert bead_input._is_build_review(step, target) is (
        "criteria" in context
    )


def test_declared_order_drives_the_rendered_order():
    """Eine andere Reihenfolge im Ablauf ändert die Übergabe ohne
    Codeänderung."""
    raw = copy.deepcopy(read_raw("planning"))
    implement = next(p for p in raw["phase"] if p["id"] == "implement")
    implement["context"]["review"] = [
        {"use": "criteria"},
        {"use": "finding_classes"},
    ]
    other = PlanningFlow(parse_flow(raw))
    issue = bead_input.BeadInput(
        id="x-1",
        title="T",
        description="D",
        design="E",
        acceptance_criteria="1. a\n2. b",
        source_refs=["a.md"],
    )
    text = render_handoff(issue, Step.REVIEW, flow=other)
    assert text.index("requirement_ref:") < text.index("Befundklassen:")
