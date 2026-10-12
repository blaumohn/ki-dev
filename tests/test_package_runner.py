"""Generischer Runner: Bindungen, Konformität und Abbruchfenster."""

from dataclasses import replace

import pytest

from ki_dev.flow.binding import (
    BindingError,
    OperationFailure,
    OperationSpec,
    parse_bindings,
)
from ki_dev.flow.model import FlowError, parse_flow
from ki_dev.run_store import RunStore, RunStoreError
from ki_dev.runner.bound import BoundOperations
from ki_dev.runner.events import check_conformance
from ki_dev.runner.package import PackageRunner
from ki_dev.runner.protocol import RUN_DOC
from tests.package_fixtures import catalog, raw_flow, text_flow


def runner(tmp_path, name="normalize", specs=None):
    flow = text_flow(name)
    operations = BoundOperations(flow.bindings, specs or catalog())
    return PackageRunner(flow, operations, RunStore(tmp_path, name))


@pytest.mark.parametrize(
    ("name", "expected"),
    [("normalize", "Hallo Welt"), ("uppercase", "  HALLO   WELT  ")],
)
def test_two_flows_share_runner_and_pattern(
    tmp_path, name, expected
):
    run = runner(tmp_path, name)
    result = run.start({"source": "  Hallo   Welt  "})
    assert result["state"] == "accepted"
    assert result["data"]["text"] == expected
    assert run.resume() == result
    assert (
        check_conformance(run.flow, run.store.load_events(), RUN_DOC)
        == []
    )
    assert {row["region"] for row in run.store.load_events()} == {
        "ablauf",
        "operation",
        "halt",
    }


def test_review_event_routes_in_dsl(tmp_path):
    result = runner(tmp_path).start({"source": "   "})
    assert result["state"] == "rejected"
    assert result["data"]["decision"] == {"event": "empty"}


@pytest.mark.parametrize("value", [None, 42, {}, True])
def test_input_contract_fails_before_service(tmp_path, value):
    specs = catalog()
    spec = specs["text.normalize"]
    calls = []
    specs["text.normalize"] = replace(
        spec, execute=lambda x: calls.append(x)
    )
    with pytest.raises(BindingError, match="input"):
        runner(tmp_path, specs=specs).start({"source": value})
    assert calls == []


def test_unknown_service_is_rejected_before_start():
    flow = text_flow()
    with pytest.raises(BindingError, match="unbekannte Operation"):
        BoundOperations(flow.bindings, {})


@pytest.mark.parametrize(
    "change",
    [
        {"input": "source"},
        {"success": None},
        {"events": ["PASS"]},
        {"typo": True},
        {"do": "__import__('os')"},
    ],
)
def test_binding_schema_rejects_ambiguous_or_invalid_data(change):
    raw = {
        "do": "text.normalize",
        "input": ["source"],
        "output": "text",
        "success": "done",
        **change,
    }
    with pytest.raises(BindingError):
        parse_bindings({"transform": raw})


def test_unknown_result_event_is_rejected(tmp_path):
    specs = catalog()
    specs["text.review"] = replace(
        specs["text.review"],
        execute=lambda _: {"event": "invented"},
    )
    with pytest.raises(BindingError, match="output"):
        runner(tmp_path, specs=specs).start({"source": "x"})


def test_crash_after_artifact_does_not_repeat_effect(
    tmp_path, monkeypatch
):
    calls = []
    specs = catalog()
    specs["text.normalize"] = replace(
        specs["text.normalize"],
        execute=lambda x: calls.append(x) or x.strip(),
    )
    original = RunStore.write_artifact

    def crash(store, operation_id, value):
        original(store, operation_id, value)
        raise SystemExit("nach Artefakt, vor Übergang")

    with monkeypatch.context() as patch:
        patch.setattr(RunStore, "write_artifact", crash)
        with pytest.raises(SystemExit):
            runner(tmp_path, specs=specs).start({"source": " x "})
    result = runner(tmp_path, specs=specs).resume()
    assert result["state"] == "accepted"
    assert calls == [" x "]


def test_uncertain_operation_needs_reconciliation(tmp_path):
    run = runner(tmp_path)
    states = dict(run.flow.states)
    state = states["produce"]
    states["produce"] = replace(
        state,
        operations=(replace(state.operations[0], repeatable=False),),
    )
    flow = replace(run.flow, states=states)
    calls = []

    def crash(value):
        calls.append(value)
        raise SystemExit("Wirkung ohne Artefakt")

    specs = catalog()
    specs["text.normalize"] = replace(
        specs["text.normalize"], execute=crash
    )
    operations = BoundOperations(flow.bindings, specs)
    run = PackageRunner(flow, operations, run.store)
    with pytest.raises(SystemExit):
        run.start({"source": "x"})
    assert run.resume()["status"] == "uncertain"
    assert run.resume()["status"] == "uncertain"
    assert calls == ["x"]
    assert run.reconcile("x")["state"] == "accepted"
    assert calls == ["x"]


def test_changed_package_cannot_resume(tmp_path):
    run = runner(tmp_path)
    run.start({"source": "x"})
    changed = replace(run.flow, name="different")
    other = PackageRunner(changed, run.operations, run.store)
    with pytest.raises(RunStoreError, match="verändert"):
        other.resume()


def test_failure_event_is_persisted_before_transition(
    tmp_path, monkeypatch
):
    raw = {
        "name": "failure",
        "start": "work",
        "final": ["rejected"],
        "vocabulary": {
            "kinds": ["machine", "final"],
            "events": ["done", "broken"],
            "operations": ["produce"],
        },
        "op": {
            "produce": {
                "do": "test.fail",
                "input": [],
                "output": "result",
                "success": "done",
            }
        },
        "state": [
            {
                "id": "work",
                "kind": "machine",
                "operation": [{"do": "produce", "failure": "broken"}],
            },
            {"id": "rejected", "kind": "final"},
        ],
        "transition": [
            {"source": "work", "target": "rejected", "event": e}
            for e in ("done", "broken")
        ],
    }
    flow = parse_flow(raw)
    calls = []

    def fail():
        calls.append(1)
        raise OperationFailure("technisch gescheitert")

    ops = BoundOperations(
        flow.bindings,
        {
            "test.fail": OperationSpec(fail, {"type": "array"}, {}),
        },
    )
    run = PackageRunner(flow, ops, RunStore(tmp_path, "failure"))
    original = RunStore.write_artifact

    def crash(store, operation_id, value):
        original(store, operation_id, value)
        raise SystemExit

    with monkeypatch.context() as patch:
        patch.setattr(RunStore, "write_artifact", crash)
        with pytest.raises(SystemExit):
            run.start({})
    assert run.resume()["state"] == "rejected"
    assert calls == [1]


def test_pattern_override_must_name_existing_local_state():
    raw = raw_flow()
    raw["phase"][0]["operation"]["typo"] = "transform"
    with pytest.raises(FlowError, match="operation.typo"):
        parse_flow(raw)
