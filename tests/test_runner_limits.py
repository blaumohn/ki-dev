"""Grenzwerte als Daten des Laufs (ki-dev-ablauf-ige.6.4.1): beim
Start einmal gesetzt, im Datensatz gespeichert, im Modell lesbar."""

import math

import pytest

from ki_dev.flow.binding import BindingError
from ki_dev.flow.model import parse_flow
from ki_dev.flow.review_flow import ReviewFlow
from ki_dev.flow_ops.review.answers import ReviewOps
from ki_dev.flow_ops.review.model import ReviewModel
from ki_dev.run_store import RunStore
from ki_dev.runner.bound import BoundOperations
from ki_dev.runner.limits import (
    EMPTY_FLOW_SCHEMA,
    ROLE_DEFAULTS,
    RUN_DEFAULTS,
    resolve,
)
from ki_dev.runner.package import PackageRunner
from ki_dev.runner.protocol import RunModel
from tests.package_fixtures import catalog, raw_flow, text_flow

DEFAULTS = {
    "run": {
        "max_agent_calls": 6,
        "max_total_tokens": 1_000_000,
        "max_claude_cost_usd": 3.0,
        "min_remaining_percent": 10.0,
        "process_retries": 3,
        "protocol_attempts": 3,
    },
    "role": {},
    "flow": {},
}
FLOW = {"rounds": 5}
FLOW_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"rounds": {"type": "integer", "minimum": 1}},
}


def _resolve(given, roles=()):
    return resolve(given, roles, FLOW, FLOW_SCHEMA)


def test_defaults_fill_every_part():
    assert resolve({}, (), {}, EMPTY_FLOW_SCHEMA) == DEFAULTS
    limits = _resolve({}, ["worker", "review", "worker"])
    assert limits["role"] == {
        "review": ROLE_DEFAULTS,
        "worker": ROLE_DEFAULTS,
    }
    assert limits["flow"] == {"rounds": 5}


def test_given_values_replace_only_their_defaults():
    limits = _resolve(
        {
            "run": {"max_agent_calls": 2},
            "role": {"worker": {"max_context_tokens": 1000}},
            "flow": {"rounds": 1},
        },
        ["worker", "review"],
    )
    assert limits["run"] == {**RUN_DEFAULTS, "max_agent_calls": 2}
    assert limits["role"]["worker"] == {
        **ROLE_DEFAULTS,
        "max_context_tokens": 1000,
    }
    assert limits["role"]["review"] == ROLE_DEFAULTS
    assert limits["flow"] == {"rounds": 1}


@pytest.mark.parametrize(
    ("given", "path"),
    [
        ({"run": {"foo": 1}}, "limits.run.foo"),
        ({"foo": {}}, "limits.foo"),
        ({"role": {"other": {}}}, "limits.role.other"),
        ({"role": {"worker": {"foo": 1}}}, "limits.role.worker.foo"),
        ({"flow": {"foo": 1}}, "limits.flow.foo"),
    ],
)
def test_unknown_key_names_its_path(given, path):
    with pytest.raises(BindingError) as error:
        _resolve(given, ["worker"])
    assert str(error.value).startswith(f"{path}:")


@pytest.mark.parametrize(
    ("given", "path"),
    [
        ({"run": {"max_agent_calls": 0}}, "limits.run.max_agent_calls"),
        (
            {"run": {"process_retries": 1.5}},
            "limits.run.process_retries",
        ),
        (
            {"run": {"max_total_tokens": True}},
            "limits.run.max_total_tokens",
        ),
        (
            {"run": {"max_claude_cost_usd": 0}},
            "limits.run.max_claude_cost_usd",
        ),
        (
            {"run": {"max_claude_cost_usd": math.inf}},
            "limits.run.max_claude_cost_usd",
        ),
        (
            {"run": {"min_remaining_percent": 100}},
            "limits.run.min_remaining_percent",
        ),
        (
            {"run": {"min_remaining_percent": math.nan}},
            "limits.run.min_remaining_percent",
        ),
        (
            {"role": {"worker": {"max_context_tokens": -1}}},
            "limits.role.worker.max_context_tokens",
        ),
        (
            {
                "role": {
                    "worker": {"max_usage_delta_percentage_points": 0}
                }
            },
            "limits.role.worker.max_usage_delta_percentage_points",
        ),
        ({"flow": {"rounds": 0}}, "limits.flow.rounds"),
        ({"run": []}, "limits.run"),
    ],
)
def test_invalid_value_names_path_not_value(given, path):
    with pytest.raises(BindingError) as error:
        _resolve(given, ["worker"])
    message = str(error.value)
    assert message.startswith(path)
    assert "1.5" not in message and "inf" not in message


def runner(tmp_path, flow=None, model=RunModel):
    flow = flow or text_flow()
    operations = BoundOperations(flow.bindings, catalog())
    return PackageRunner(
        flow,
        operations,
        RunStore(tmp_path, "limits"),
        model=model,
        flow_limits=FLOW,
        flow_limits_schema=FLOW_SCHEMA,
    )


def test_new_run_saves_default_limits(tmp_path):
    run = runner(tmp_path)
    run.start({"source": "x"})
    record = run.store.load_record()
    assert record["limits"] == {**DEFAULTS, "flow": {"rounds": 5}}


def test_given_limits_are_saved_and_resumed(tmp_path):
    run = runner(tmp_path)
    run.start({"source": "x"}, limits={"run": {"max_agent_calls": 2}})
    expected = {
        **DEFAULTS,
        "run": {**RUN_DEFAULTS, "max_agent_calls": 2},
        "flow": {"rounds": 5},
    }
    assert run.store.load_record()["limits"] == expected
    again = runner(tmp_path)
    again.resume()
    assert again.model.limits == expected


def test_unknown_limit_fails_before_the_run(tmp_path):
    run = runner(tmp_path)
    with pytest.raises(BindingError, match=r"^limits\.run\.foo:"):
        run.start({"source": "x"}, limits={"run": {"foo": 1}})
    assert run.store.load_record() is None


def test_roles_of_the_flow_get_role_limits(tmp_path):
    raw = raw_flow()
    steps = raw["pattern"]["produce_check"]["state"]
    steps[0]["operation"][0]["role"] = "writer"
    run = runner(tmp_path, parse_flow(raw))
    run.start({"source": "x"})
    limits = run.store.load_record()["limits"]
    assert limits["role"] == {"writer": ROLE_DEFAULTS}


class CallsModel(RunModel):
    def many_calls(self) -> bool:
        return self.limits["run"]["max_agent_calls"] > 2


def _guarded_flow(guard="many_calls"):
    """Die Prüfung nimmt PASS nur, wenn der Wächter gilt (hier: er
    liest aus den Grenzwerten mehr als zwei Aufrufe)."""
    raw = raw_flow()
    raw["vocabulary"]["guards"] = [guard]
    edges = raw["pattern"]["produce_check"]["transition"]
    passed = next(e for e in edges if e["event"] == "PASS")
    passed["cond"] = [guard]
    edges.append(
        {
            "source": "check",
            "event": "PASS",
            "target": "rejected",
            "cond": [f"!{guard}"],
        }
    )
    return parse_flow(raw)


@pytest.mark.parametrize(
    ("limits", "state"),
    [(None, "accepted"), ({"run": {"max_agent_calls": 2}}, "rejected")],
)
def test_guard_reads_limits(tmp_path, limits, state):
    run = runner(tmp_path, _guarded_flow(), CallsModel)
    assert run.start({"source": "x"}, limits=limits)["state"] == state


def test_review_model_reads_flow_limits_of_review_ops():
    flow = text_flow()
    ops = ReviewOps(ReviewFlow(flow))
    limits = resolve({}, (), ops.flow_limits, ops.flow_limits_schema)
    model = ReviewModel(limits=limits)
    assert model.limits["flow"] == {
        "changes_rounds": 5,
        "worker_attempts": 12,
        "max_failed_corrections": 2,
        "max_stagnant_changes": 3,
    }
    with pytest.raises(BindingError, match=r"^limits\.flow\.foo:"):
        resolve(
            {"flow": {"foo": 1}},
            (),
            ops.flow_limits,
            ops.flow_limits_schema,
        )


def test_review_model_reads_limits_in_a_run(tmp_path):
    flow = _guarded_flow("full_checks")
    run = PackageRunner(
        flow,
        BoundOperations(flow.bindings, catalog()),
        RunStore(tmp_path, "review"),
        model=ReviewModel,
        flow_limits=ReviewOps.flow_limits,
        flow_limits_schema=ReviewOps.flow_limits_schema,
    )
    run.start({"source": "x"}, limits={"flow": {"changes_rounds": 1}})
    assert isinstance(run.model, ReviewModel)
    assert run.model.limits["flow"]["changes_rounds"] == 1
    assert run.model.limits["flow"]["worker_attempts"] == 12
