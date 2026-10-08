"""Planungsschleife: Startereignis, Maschinenzustände, Halt am turn."""

from __future__ import annotations

import pytest

from ki_dev.flow.model import FlowError, load_flow
from ki_dev.runner.planning import (
    ASK,
    TURN,
    PlanningContext,
    bind_planning,
    drive,
    with_facts,
)

BOUND = bind_planning(load_flow("planning"))


def _checks(event, facts=frozenset({"full_checks"})):
    def run(_state, context):
        return event, with_facts(context, facts, event)

    return {"checks": run}


def _edges(halt):
    return [(t.source, t.event, t.target) for t in halt.path]


def test_passed_checks_reach_the_review_turn():
    halt = drive(BOUND, "implement", "done", _checks("checks_passed"))
    assert (halt.state, halt.operation) == ("implement.review", TURN)
    assert _edges(halt) == [
        ("implement", "done", "implement.preflight"),
        ("implement.preflight", "checks_passed", "implement.review"),
    ]
    assert halt.entry.source == "implement"


def test_failed_checks_go_to_correction():
    halt = drive(
        BOUND, "implement.correction", "done", _checks("checks_failed")
    )
    assert (halt.state, halt.operation) == (
        "implement.correction",
        TURN,
    )
    assert halt.via.event == "checks_failed"


def test_partial_checks_reach_review_but_forbid_pass():
    halt = drive(
        BOUND,
        "implement",
        "done",
        _checks("checks_partial", frozenset()),
    )
    assert halt.state == "implement.review"
    assert (
        BOUND.select("implement.review", "PASS", halt.context) is None
    )
    with pytest.raises(FlowError, match="PASS in implement.review"):
        drive(BOUND, "implement.review", "PASS", {}, halt.context)


def test_phases_without_checks_are_stubs_that_stop_at_review():
    halt = drive(BOUND, "map", "done", {})
    assert (halt.state, halt.operation) == ("map.review", TURN)


def test_human_states_halt_with_ask_and_final_ends():
    assert (
        drive(BOUND, "implement.review", "decision", {}).operation
        == ASK
    )
    final = drive(
        BOUND, "implement.review", "PASS", {}, PlanningContext()
    )
    assert (final.state, final.operation) == ("finished", None)


def test_unknown_event_is_visible():
    with pytest.raises(FlowError, match="vielleicht in map"):
        drive(BOUND, "map", "vielleicht", {})
