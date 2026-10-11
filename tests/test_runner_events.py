"""Ereignisprotokoll je Übergang: Schema, Idempotenz, Konformität je
Region (Ablauf gegen das Paket, Lauf gegen runner/run.toml)."""

from __future__ import annotations

import pytest

from ki_dev.flow.model import Transition, load_flow
from ki_dev.run_store import RunStore
from ki_dev.runner.events import (
    EventLogError,
    check_conformance,
    event_record,
    run_event_record,
    validate_record,
)
from ki_dev.runner.machine import Limits
from ki_dev.runner.run_machine import RUN_DOC
from tests.test_runner_runtime import (
    FakeReviewer,
    FakeWorker,
    _context,
    _runtime,
    _task,
)

IMPLEMENT = load_flow("implement")


def _record(**fields) -> dict[str, object]:
    (transition,) = IMPLEMENT.candidates("start", "run_started")
    record = event_record(
        line=1,
        seq=1,
        ts="2026-10-08T09:00:00+00:00",
        flow=IMPLEMENT,
        run_id="r-1",
        transition=transition,
        target="controller_step",
        adapter="ki-dev",
    )
    return {**record, **fields}


def test_a_run_logs_every_taken_edge_and_conforms(tmp_path):
    worker, reviewer = FakeWorker(), FakeReviewer(["fix", "PASS"])
    with _runtime(
        tmp_path,
        "run-log",
        worker,
        reviewer,
        [_context(1), _context(2)],
    ) as runtime:
        result = runtime.start(_task("run-log"), Limits())
    events = RunStore(tmp_path, "run-log").load_events()
    flow = [e for e in events if e["region"] == "ablauf"]

    assert result.status == "passed"
    assert [e["line"] for e in events] == list(
        range(1, len(events) + 1)
    )
    assert [e["seq"] for e in flow] == list(range(1, len(flow) + 1))
    assert flow[0]["state"] == "start"
    assert flow[-1]["target"] == "passed"
    assert {e["region"] for e in events} == {
        "ablauf", "operation", "halt",
    }
    assert events[-1]["event"] == "done.state.ablauf"
    assert check_conformance(IMPLEMENT, events, RUN_DOC) == []
    fix = next(e for e in flow if e["event"] == "fix")
    assert fix["actions"] == ["begin_correction", "drop_result"]
    assert fix["adapter"] == reviewer.spec.name


def test_pause_and_answer_are_logged_in_their_regions(tmp_path):
    """Operation, Pause und Antwort stehen als Zeilen ihrer Region im
    Protokoll; seq zählt nur den Ablauf."""
    with _runtime(
        tmp_path,
        "run-pause",
        FakeWorker(),
        FakeReviewer(["escalate", "PASS"]),
        [_context(1)],
    ) as runtime:
        runtime.start(_task("run-pause"), Limits())
    with _runtime(
        tmp_path,
        "run-pause",
        FakeWorker(),
        FakeReviewer(["PASS"]),
        [_context(1)],
    ) as resumed:
        resumed.resume("weiter")
    events = RunStore(tmp_path, "run-pause").load_events()
    halt = [
        (e["state"], e["event"], e["target"])
        for e in events
        if e["region"] == "halt"
    ]

    assert ("running", "escalation.agent", "paused_interactive") in halt
    assert ("paused_interactive", "answer", "running") in halt
    escalate = next(e for e in events if e["event"] == "escalate")
    pause = next(e for e in events if e["event"] == "escalation.agent")
    assert pause["seq"] == escalate["seq"]
    assert pause["line"] == escalate["line"] + 1
    assert check_conformance(IMPLEMENT, events, RUN_DOC) == []


def test_replayed_transition_is_not_written_twice(tmp_path):
    store = RunStore(tmp_path, "r-1")
    assert store.append_event(_record()) is True
    assert store.append_event(_record()) is False
    assert len(store.load_events()) == 1


def test_conformance_names_undeclared_edges_and_gaps():
    bogus = _record(event="PASS", target="passed")
    gap = _record(seq=2, state="worker_step")
    problems = check_conformance(IMPLEMENT, [bogus, gap])
    assert problems == [
        "0: keine Kante start --PASS--> passed",
        "1: beginnt in worker_step, vorher endete passed",
        "1: keine Kante worker_step --run_started--> controller_step",
    ]


def _run_row(line: int, state: str, event: str, target: str):
    return run_event_record(
        line=line,
        seq=0,
        ts="2026-10-08T09:00:00+00:00",
        run_id="r-1",
        region="operation",
        transition=Transition(source=state, event=event, target=target),
    )


def test_conformance_checks_each_region_against_its_definition():
    """Eine Zeile des Laufs passt nicht zum Ablauf, aber zu run.toml;
    jede Region hat ihre eigene Kette."""
    rows = [
        _record(),
        _run_row(2, "idle", "hold", "prepared"),
        _run_row(3, "prepared", "PASS", "idle"),
        _run_row(4, "started", "artifact_saved", "idle"),
    ]
    assert check_conformance(IMPLEMENT, rows, RUN_DOC) == [
        "2: keine Kante prepared --PASS--> idle",
        "3: beginnt in started, vorher endete idle",
    ]
    assert check_conformance(IMPLEMENT, rows) == [
        "1: Region operation ohne Definition",
    ]


def test_region_edge_counts_for_its_inner_states():
    """``failed`` deklariert die Region selbst: die Zeile beginnt dort,
    in einem Vorfahren des vorigen Zielzustands."""
    rows = [
        _run_row(1, "idle", "hold", "prepared"),
        _run_row(2, "operation", "failed", "idle"),
    ]
    assert check_conformance(IMPLEMENT, rows, RUN_DOC) == []


@pytest.mark.parametrize(
    ("change", "path"),
    [
        ({"line": 0}, "line: minimum"),
        ({"extra": 1}, "$: additionalProperties"),
        ({"adapter": ""}, "adapter: minLength"),
    ],
)
def test_schema_names_the_field(change, path):
    with pytest.raises(EventLogError) as excinfo:
        validate_record(_record(**change))
    assert str(excinfo.value) == path
