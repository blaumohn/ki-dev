"""Ereignisprotokoll je Übergang: Schema, Idempotenz, Konformität."""

from __future__ import annotations

import pytest

from ki_dev.flow.model import load_flow
from ki_dev.run_store import RunStore
from ki_dev.runner.events import (
    EventLogError,
    check_conformance,
    event_record,
    validate_record,
)
from ki_dev.runner.machine import Limits
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

    assert result.status == "passed"
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    assert events[0]["state"] == "start"
    assert events[-1]["target"] == "passed"
    assert check_conformance(IMPLEMENT, events) == []
    fix = next(e for e in events if e["event"] == "fix")
    assert fix["actions"] == ["begin_correction", "drop_result"]
    assert fix["adapter"] == reviewer.spec.name


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


@pytest.mark.parametrize(
    ("change", "path"),
    [
        ({"seq": 0}, "seq: minimum"),
        ({"extra": 1}, "$: additionalProperties"),
        ({"adapter": ""}, "adapter: minLength"),
    ],
)
def test_schema_names_the_field(change, path):
    with pytest.raises(EventLogError) as excinfo:
        validate_record(_record(**change))
    assert str(excinfo.value) == path
