"""Planungslauf je Bead: Start, Maschinenzustände, Halt am turn,
Datensatz über Prozessgrenzen, Antwort nur am wartenden Zustand."""

from __future__ import annotations

import copy
import json
from dataclasses import replace

import pytest

from ki_dev.flow.model import FlowError, load_flow, parse_flow, read_raw
from ki_dev.runner.planning import (
    ASK,
    TURN,
    PlanningContext,
    StaleAnswerError,
    StaleHaltError,
    allows,
    flow_digest,
    planning_runtime,
    with_facts,
)

FLOW = load_flow("planning")


STAND = {"tree": "a1b2c3d", "bead": "40"}


def _checks(event, facts=frozenset({"full_checks"})):
    def run(_state, context):
        return event, with_facts(context, facts, event, STAND)

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
        attempt = runtime.start("implement", "done").attempt
    with planning_runtime(FLOW, tmp_path, "b") as runtime:
        assert runtime.waiting() == ("implement.review", frozenset())
        with pytest.raises(FlowError, match="PASS in implement.review"):
            runtime.resume("PASS", attempt=attempt)
        halt = runtime.resume("fix", attempt=attempt)
    assert (halt.state, _edges(halt)) == (
        "implement.correction",
        [("implement.review", "fix", "implement.correction")],
    )


def test_phases_without_checks_are_stubs_that_stop_at_review(tmp_path):
    with planning_runtime(FLOW, tmp_path, "b") as runtime:
        halt = runtime.start("map", "done")
    assert (halt.state, halt.operation) == ("map.review", TURN)


def test_human_states_halt_with_ask_and_final_ends(tmp_path):
    with planning_runtime(
        FLOW, tmp_path, "b", _checks("checks_passed")
    ) as runtime:
        assert (
            runtime.start("implement.review", "decision").operation
            == ASK
        )
        waiting = runtime.start("implement", "done")
        final = runtime.resume("PASS", STAND, waiting.attempt)
        assert (final.state, final.operation) == ("finished", None)
        assert final.attempt is None
        with pytest.raises(FlowError, match="wartet auf keine Antwort"):
            runtime.resume("done")


def test_pass_without_checks_is_not_allowed(tmp_path):
    """Tatsachen beginnen leer: ohne Vorlauf trägt der Wächter
    full_checks kein PASS."""
    with (
        planning_runtime(FLOW, tmp_path, "b") as runtime,
        pytest.raises(FlowError, match="PASS in implement.review"),
    ):
        runtime.start("implement.review", "PASS")


def test_pass_on_changed_stand_runs_checks_again(tmp_path):
    """Synchron wie freeze bei run: weicht der Stand ab, nimmt PASS die
    Kante zurück in den Vorlauf und hält wieder am Review."""
    with planning_runtime(
        FLOW, tmp_path, "b", _checks("checks_passed")
    ) as runtime:
        waiting = runtime.start("implement", "done")
        halt = runtime.resume(
            "PASS", {**STAND, "tree": "e4f5a6b"}, waiting.attempt
        )
    assert (halt.state, halt.operation) == ("implement.review", TURN)
    assert _edges(halt) == [
        ("implement.review", "PASS", "implement.preflight"),
        ("implement.preflight", "checks_passed", "implement.review"),
    ]


def _taken(state, event, context):
    """Kante, die die Bibliothek mit diesen Laufdaten nimmt."""
    from ki_dev.fsm import Durable
    from ki_dev.runner.planning import PlanningModel, _chart

    machine = Durable(
        _chart(FLOW),
        PlanningModel(context),
        {"state": [state], "history": {}},
    )
    taken = machine.send(event)
    return FLOW.edge(taken.owner, taken.index, state)


def test_unchanged_guard_compares_without_io():
    review = "implement.review"
    same = PlanningContext(frozenset({"full_checks"}), checked=STAND)
    for current, target in (
        (STAND, "finished"),
        ({**STAND, "bead": "41"}, "implement.preflight"),
        (None, "implement.preflight"),
    ):
        context = replace(same, current=current)
        (edge,) = [
            t
            for t in FLOW.candidates(review, "PASS")
            if t.target == target
        ]
        assert allows(FLOW, review, "PASS", context)
        assert _taken(review, "PASS", context) == edge


def _renamed_graph_phase() -> object:
    raw = copy.deepcopy(read_raw("planning"))
    for phase in raw["phase"]:
        if phase["id"] == "graph":
            phase["id"] = "plan"
        if phase.get("next") == "graph":
            phase["next"] = "plan"
    return parse_flow(raw)


def test_halt_from_other_flow_is_named_not_a_keyerror(tmp_path):
    """Nach einer Umbenennung (wie build → implement) passt ein alter
    Halt nicht mehr: verständlicher Fehler; --step beginnt neu."""
    with planning_runtime(_renamed_graph_phase(), tmp_path, "b") as old:
        old.start("plan", None)
    with planning_runtime(FLOW, tmp_path, "b") as runtime:
        for call in (runtime.waiting, lambda: runtime.resume("done")):
            with pytest.raises(StaleHaltError, match="--step neu"):
                call()
        assert runtime.start("map", None).state == "map"
        assert runtime.waiting() == ("map", frozenset())


def test_hint_texts_do_not_change_the_flow_digest():
    raw = copy.deepcopy(read_raw("planning"))
    raw["phase"][0]["hint"]["review"]["fix"] = "anderer Text"
    assert flow_digest(parse_flow(raw)) == flow_digest(FLOW)
    assert flow_digest(_renamed_graph_phase()) != flow_digest(FLOW)


def test_unknown_event_is_visible_and_changes_nothing(tmp_path):
    with planning_runtime(FLOW, tmp_path, "b") as runtime:
        attempt = runtime.start("map", None).attempt
        with pytest.raises(FlowError, match="vielleicht in map"):
            runtime.resume("vielleicht", attempt=attempt)
        halt = runtime.resume("done", attempt=attempt)
        assert halt.state == "map.review"


def test_answer_needs_the_waiting_attempt(tmp_path):
    """Eine Antwort gilt nur für den Versuch, für den die Übergabe
    ausgegeben wurde: fehlt die Kennung oder ist sie fremd, bleibt der
    Checkpoint unverändert."""
    with planning_runtime(FLOW, tmp_path, "b") as runtime:
        first = runtime.start("map", None)
        before = runtime.waiting()
        with pytest.raises(StaleAnswerError, match="attempt fehlt"):
            runtime.resume("done")
        with pytest.raises(StaleAnswerError, match="gehört nicht"):
            runtime.resume("done", attempt="b:99")
        assert runtime.waiting() == before
        review = runtime.resume("done", attempt=first.attempt)
    assert review.state == "map.review"
    assert review.attempt not in (None, first.attempt)


def test_new_start_never_reuses_an_old_attempt(tmp_path):
    with planning_runtime(FLOW, tmp_path, "b") as runtime:
        old = runtime.start("map", None).attempt
        new = runtime.start("map", None).attempt
        assert new != old
        with pytest.raises(StaleAnswerError):
            runtime.resume("done", attempt=old)
        assert runtime.resume("done", attempt=new).state == "map.review"


def test_generated_statechart_has_exactly_the_planning_states():
    """Muster erzeugen ``[statechart]`` (Programmierleitlinie: genau
    eine maßgebliche Quelle); Zustände und Kanten entsprechen der
    flachen Sicht."""
    states = FLOW.statechart["states"]
    assert set(states) == set(FLOW.states)
    for state in FLOW.states:
        native = states[state].get("transitions", [])
        view = FLOW.outgoing(state)
        assert [(e["event"], e["target"]) for e in native] == [
            (t.event, t.target) for t in view
        ]


def test_record_survives_the_process_boundary(tmp_path):
    with planning_runtime(FLOW, tmp_path, "b") as runtime:
        attempt = runtime.start("map", None).attempt
    record = json.loads((tmp_path / "record.json").read_text())
    assert record["run"]["state"] == ["map"]
    assert record["waiting"] == TURN
    with planning_runtime(FLOW, tmp_path, "b") as runtime:
        assert runtime.resume("done", attempt=attempt).state == (
            "map.review"
        )


def test_a_second_writer_is_rejected(tmp_path):
    with (
        planning_runtime(FLOW, tmp_path, "b"),
        pytest.raises(FlowError, match="bereits"),
        planning_runtime(FLOW, tmp_path, "b"),
    ):
        pass


def test_halt_without_attempt_is_stale_not_a_keyerror(tmp_path):
    """Ein Halt aus der Zeit vor der Versuchskennung: verständlicher
    Fehler wie bei einem anderen Ablaufstand; --step beginnt neu."""
    with planning_runtime(FLOW, tmp_path, "b") as runtime:
        runtime.start("map", None)
        path = tmp_path / "record.json"
        record = json.loads(path.read_text())
        record.pop("attempt")
        path.write_text(json.dumps(record))
        for call in (
            runtime.waiting,
            lambda: runtime.resume("done", attempt="b:1"),
            lambda: runtime.advance("done"),
        ):
            with pytest.raises(StaleHaltError, match="--step neu"):
                call()
