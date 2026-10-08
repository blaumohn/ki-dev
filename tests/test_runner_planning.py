"""Planungs-Thread je Bead: Start, Maschinenzustände, interrupt am turn,
Checkpoint über Prozessgrenzen, Antwort nur am wartenden Zustand."""

from __future__ import annotations

import pytest

from ki_dev.flow.model import FlowError, load_flow
from ki_dev.runner import graph
from ki_dev.runner.planning import (
    ASK,
    TURN,
    planning_runtime,
    with_facts,
)

FLOW = load_flow("planning")


def _checks(event, facts=frozenset({"full_checks"})):
    def run(_state, context):
        return event, with_facts(context, facts, event)

    return {"checks": run}


def _edges(halt):
    return [(t.source, t.event, t.target) for t in halt.path]


def test_passed_checks_reach_the_review_turn(tmp_path):
    with planning_runtime(
        FLOW, tmp_path, "b", _checks("checks_passed")
    ) as runtime:
        halt = runtime.start("implement", "done")
    assert (halt.state, halt.operation) == ("implement.review", TURN)
    assert _edges(halt) == [
        ("implement", "done", "implement.preflight"),
        ("implement.preflight", "checks_passed", "implement.review"),
    ]
    assert halt.context.outcome == "checks_passed"


def test_failed_checks_go_to_correction(tmp_path):
    with planning_runtime(
        FLOW, tmp_path, "b", _checks("checks_failed")
    ) as runtime:
        halt = runtime.start("implement.correction", "done")
    assert (halt.state, halt.operation) == (
        "implement.correction",
        TURN,
    )
    assert halt.via.event == "checks_failed"


def test_checkpoint_survives_the_process_and_keeps_the_guard(tmp_path):
    """Teillauf in einem Aufruf, PASS im nächsten: der Checkpoint trägt
    die Tatsachen, der Wächter weist PASS ab, der Zustand bleibt."""
    partial = _checks("checks_partial", frozenset())
    with planning_runtime(FLOW, tmp_path, "b", partial) as runtime:
        runtime.start("implement", "done")
    with planning_runtime(FLOW, tmp_path, "b") as runtime:
        assert runtime.waiting() == ("implement.review", frozenset())
        with pytest.raises(FlowError, match="PASS in implement.review"):
            runtime.resume("PASS")
        halt = runtime.resume("fix")
    assert (halt.state, _edges(halt)) == (
        "implement.correction",
        [("implement.review", "fix", "implement.correction")],
    )


def test_phases_without_checks_are_stubs_that_stop_at_review(tmp_path):
    with planning_runtime(FLOW, tmp_path, "b") as runtime:
        halt = runtime.start("map", "done")
    assert (halt.state, halt.operation) == ("map.review", TURN)


def test_human_states_halt_with_ask_and_final_ends(tmp_path):
    with planning_runtime(FLOW, tmp_path, "b") as runtime:
        assert (
            runtime.start("implement.review", "decision").operation
            == ASK
        )
        final = runtime.start("implement.review", "PASS")
        assert (final.state, final.operation) == ("finished", None)
        with pytest.raises(FlowError, match="wartet auf keine Antwort"):
            runtime.resume("done")


def test_unknown_event_is_visible_and_changes_nothing(tmp_path):
    with planning_runtime(FLOW, tmp_path, "b") as runtime:
        runtime.start("map", None)
        with pytest.raises(FlowError, match="vielleicht in map"):
            runtime.resume("vielleicht")
        assert runtime.resume("done").state == "map.review"


def test_run_and_step_share_the_graph_translation():
    """Ein Ausführer: beide Laufzeiten bauen ihren Graphen mit
    compile_flow aus ihrer Ablaufdatei."""
    import ki_dev.runner.planning as planning
    import ki_dev.runner.runtime as runtime

    assert runtime.compile_flow is graph.compile_flow
    assert planning.compile_flow is graph.compile_flow
