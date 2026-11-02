"""Messung vor ``start`` (ki-dev-ablauf-ige.6.4.3): der Adapter misst,
die SM hält (Regel 4)."""

from __future__ import annotations

import json
import math
from dataclasses import asdict

import pytest

from ki_dev.adapter.agent import AgentSession
from ki_dev.adapter.contract import TurnPrompt
from ki_dev.adapter.executors.claude_cli import ClaudeCliAdapter
from ki_dev.adapter.executors.contract import (
    ContextMeasurement,
    ContextStatus,
    Effort,
    ExecutorSpec,
    Measure,
    QuotaMeasurement,
    QuotaStatus,
    TurnResult,
    TurnStatus,
)
from ki_dev.adapter.mock import MockAnswers
from ki_dev.flow_ops.review.model import ReviewModel
from ki_dev.run_store import RunStore
from ki_dev.runner.bound import BoundOperations
from ki_dev.runner.dispatch import Dispatch
from ki_dev.runner.limits import limit_reasons
from ki_dev.runner.meter import Meter
from ki_dev.runner.package import PackageRunner
from ki_dev.runner.safety import CallLedger, SafetyLimits, SafetyStop
from tests.executor_specs import LOCAL
from tests.test_runner_dispatch import FLOW, _answer, _catalog, _read

ALL = ExecutorSpec(
    "claude", "claude-cli", frozenset(Measure)
)
FAR = 4_000_000_000
USAGE = {
    "input_tokens": 10,
    "output_tokens": 20,
    "cache_read_input_tokens": 100,
    "cache_creation_input_tokens": 30,
    "cost_usd": 0.2,
}


class Measuring:
    """Fake-Executor mit allen Messungen; zählt die Aufrufe."""

    spec = ALL
    session_id = "s-1"

    def __init__(self, context=1_000, used=50.0, answers=()):
        self.context = context
        self.used = used
        self.answers = list(answers)
        self.asked = 0

    def measure_context(self):
        return self.context

    def measure_quota(self):
        if self.used is None:
            return QuotaMeasurement(QuotaStatus.PENDING)
        return QuotaMeasurement(
            QuotaStatus.MEASURED, self.used, FAR
        )

    def ask(self, request):
        self.asked += 1
        return self.answers.pop(0).replace(
            "{attempt}", request.key
        )


def _context(tokens):
    if isinstance(tokens, ContextMeasurement):
        return tokens
    return ContextMeasurement(ContextStatus.MEASURED, tokens)


def _runner(tmp_path, executors, *, measure=True):
    store = RunStore(tmp_path, "m")
    turns = Dispatch(
        FLOW,
        executors,
        render=lambda h: f"Übergabe {h.state} {h.attempt}",
        read=_read,
        workdir=tmp_path,
        meter=Meter(store, executors) if measure else None,
    )
    return PackageRunner(
        FLOW,
        BoundOperations(FLOW.bindings, _catalog()),
        store,
        model=ReviewModel,
        turns=turns,
    )


def _fake(**kwargs):
    fake = Measuring(**kwargs)
    inner = fake.measure_context
    fake.measure_context = lambda: _context(inner())
    return fake


def _rows(run, event):
    return [
        e
        for e in run.store.load_events()
        if e["event"] == event and e["region"] == "operation"
    ]


def test_limits_stop_before_start_without_ask(tmp_path):
    worker = _fake(context=85_000, used=92.0, answers=[])
    run = _runner(tmp_path, {"worker": worker})
    result = run.start({})
    assert result["status"] == "stopped"
    assert worker.asked == 0
    reason = result["reason"]
    assert "Kontextgrenze erreicht für worker" in reason
    assert "Kontingentreserve unterschritten" in reason
    assert len(_rows(run, "measured")) == 1
    assert _rows(run, "start") == []


def test_below_limits_runs_through(tmp_path):
    worker = _fake(answers=[_answer("done")])
    review = MockAnswers(LOCAL, [_answer("PASS")])
    run = _runner(tmp_path, {"worker": worker, "review": review})
    result = run.start({})
    assert result["status"] == result["state"] == "finished"
    assert worker.asked == 1
    assert len(_rows(run, "measured")) == 1


def test_resume_measures_again(tmp_path):
    worker = _fake(
        context=85_000, answers=[_answer("done")]
    )
    review = MockAnswers(LOCAL, [_answer("PASS")])
    run = _runner(tmp_path, {"worker": worker, "review": review})
    assert run.start({})["status"] == "stopped"
    worker.context = 1_000
    assert run.resume()["state"] == "finished"
    assert len(_rows(run, "measured")) == 2


def test_executor_without_measures_leaves_no_row(tmp_path):
    worker = MockAnswers(LOCAL, [_answer("done")])
    review = MockAnswers(LOCAL, [_answer("PASS")])
    run = _runner(tmp_path, {"worker": worker, "review": review})
    assert run.start({})["state"] == "finished"
    assert _rows(run, "measured") == []


def test_unavailable_context_stops_with_the_gap(tmp_path):
    worker = _fake(answers=[])
    worker.measure_context = lambda: ContextMeasurement(
        ContextStatus.UNAVAILABLE, detail="Ablage fehlt"
    )
    run = _runner(tmp_path, {"worker": worker})
    result = run.start({})
    assert result["status"] == "stopped"
    assert worker.asked == 0
    assert result["reason"] == (
        "Kontextmessung für worker (executor=claude, session=s-1) "
        "fehlt: Ablage fehlt; kein Aufruf ohne Nachweis"
    )


def test_measurement_values(tmp_path):
    store = RunStore(tmp_path, "m")
    worker = _fake(context=85_000, used=92.0)
    measured = Meter(store, {"review": worker}).measure("review")
    assert measured == {
        "role": "review",
        "context": 85_000,
        "quota_left": 8.0,
        "quota_delta": 0.0,
        "calls": 0,
        "tokens": 0,
        "cost_usd": 0.0,
        "gaps": [],
    }
    worker.used = 95.0
    again = Meter(store, {"review": worker}).measure("review")
    assert again["quota_left"] == 5.0
    assert again["quota_delta"] == 3.0
    mock = MockAnswers(LOCAL, [])
    assert Meter(store, {"review": mock}).measure("review") is None


def test_pending_quota_is_not_measured(tmp_path):
    worker = _fake(used=None)
    measured = Meter(
        RunStore(tmp_path, "m"), {"review": worker}
    ).measure("review")
    assert measured["quota_left"] is measured["quota_delta"] is None
    assert measured["gaps"] == []


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
@pytest.mark.parametrize(
    "field", ["cost_usd", "quota_left", "quota_delta"]
)
def test_nonfinite_measurements_are_gaps(value, field):
    measurement = {"role": "worker", field: value}
    limits = {
        "run": {
            "min_remaining_percent": 10,
            "max_claude_cost_usd": 3,
            "max_agent_calls": 6,
            "max_fresh_tokens": 100,
        },
        "role": {},
    }
    reasons = limit_reasons(measurement, limits)
    assert any(field in reason for reason in reasons)


def test_nonfinite_measurement_keeps_the_other_reasons():
    measurement = {"role": "worker", "cost_usd": math.nan, "calls": 6}
    limits = {
        "run": {"max_agent_calls": 6, "max_claude_cost_usd": 3},
        "role": {},
    }
    reasons = limit_reasons(measurement, limits)
    assert any("cost_usd" in reason for reason in reasons)
    assert "Aufrufgrenze erreicht: 6" in reasons


def test_meter_without_role_is_not_measured(tmp_path):
    worker = _fake()
    meter = Meter(RunStore(tmp_path, "m"), {None: worker})
    assert meter.measure(None) is None


@pytest.mark.parametrize(
    ("used", "resets"),
    [(None, FAR), (math.nan, FAR), (50.0, None)],
)
def test_invalid_measured_quota_is_a_gap(tmp_path, used, resets):
    worker = _fake()

    class RawQuota:
        status = QuotaStatus.MEASURED
        used_percent = used
        resets_at = resets
        detail = ""

    worker.measure_quota = lambda: RawQuota()
    measured = Meter(
        RunStore(tmp_path, "m"), {"review": worker}
    ).measure("review")
    assert measured["gaps"]
    assert measured.get("quota_left") is None


def test_agent_session_measures_through_real_adapter_and_fake_cli(
    tmp_path, monkeypatch
):
    sessions = tmp_path / ".claude" / "projects"
    session_file = sessions / "project" / "session-1.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_text(
        json.dumps({
            "type": "assistant",
            "message": {
                "model": "claude-test",
                "usage": {
                    "input_tokens": 100,
                    "cache_read_input_tokens": 20,
                    "cache_creation_input_tokens": 3,
                },
            },
        }) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(tmp_path))

    adapter = ClaudeCliAdapter(
        executable="fake-claude",
        quota_dir=tmp_path / "quota",
        runner=lambda _argv, **_kwargs: TurnResult(
            TurnStatus.OK, 0,
                '{"type":"rate_limit_event","rate_limit_info":'
                '{"unifiedWindows":{"five_hour":{"utilization":'
                '0.25,"resetsAt":4000000000}}}}\n'
                '{"type":"result","subtype":"success",'
                '"is_error":false,"result":"ok","num_turns":1,'
                '"session_id":"session-1",'
            '"total_cost_usd":0.01,"usage":{"input_tokens":10,'
            '"output_tokens":2,"cache_read_input_tokens":0,'
                    '"cache_creation_input_tokens":0}}',
            "", (), 0.01,
        ),
    )
    adapter.probe_executed_version = (
        lambda *_args: adapter.cli_version_pin
    )
    spec = ExecutorSpec("claude", "claude-cli", frozenset(
        {Measure.CONTEXT, Measure.QUOTA}
    ))
    session = AgentSession(
        adapter, "session-1", "model", Effort.LOW,
        spec=spec,
    )
    assert session.measure_context().tokens == 123
    prompt = TurnPrompt("try-1", "prompt", tmp_path, {})
    assert session.ask(prompt) == "ok"
    assert session.measure_quota().used_percent == 25.0


def test_unsupported_quota_is_a_gap(tmp_path):
    worker = _fake()
    worker.measure_quota = lambda: QuotaMeasurement(
        QuotaStatus.UNSUPPORTED
    )
    measured = Meter(
        RunStore(tmp_path, "m"), {"review": worker}
    ).measure("review")
    assert measured["gaps"] == [
        "Fuenfstundenkontingent-Messwert fuer review "
        "(executor=claude, session=s-1) fehlt (unsupported); "
        "kein Aufruf ohne Nachweis"
    ]


def test_codex_has_no_context(tmp_path):
    spec = ExecutorSpec(
        "codex", "codex-cli", frozenset({Measure.QUOTA})
    )
    worker = _fake()
    worker.spec = spec
    measured = Meter(
        RunStore(tmp_path, "m"), {"review": worker}
    ).measure("review")
    assert "context" not in measured
    assert "calls" not in measured


def test_totals_match_the_booked_usage(tmp_path):
    store = RunStore(tmp_path, "guard")
    store.initialize({"safety_limits": asdict(SafetyLimits())})
    ledger = CallLedger(store)
    usage = USAGE
    for number in (1, 2):
        call = f"call-{number}"
        ledger.reserve(call, "worker", True)
        ledger.finish(
            call,
            TurnResult(
                TurnStatus.OK, 0, "x", "", (), 1.0, usage=usage
            ),
            None,
        )
    totals = ledger.totals()
    assert totals["calls"] == 2
    assert totals["tokens"] == 120  # 2 x 60 frisch
    assert totals["cost_usd"] == pytest.approx(0.4)
    assert totals["gaps"] == []


def test_open_reservation_is_a_gap(tmp_path):
    store = RunStore(tmp_path, "guard")
    store.initialize({"safety_limits": asdict(SafetyLimits())})
    ledger = CallLedger(store)
    ledger.reserve("call-1", "worker", True)
    gaps = ledger.totals()["gaps"]
    assert gaps[0] == (
        "Verbrauch eines begonnenen Aufrufs ist ungeklaert"
    )
    with pytest.raises(SafetyStop, match="ungeklaert"):
        ledger.reserve("call-2", "worker", True)


def test_reserve_stops_at_the_summed_tokens(tmp_path):
    store = RunStore(tmp_path, "guard")
    limits = SafetyLimits(max_fresh_tokens=60)
    store.initialize({"safety_limits": asdict(limits)})
    ledger = CallLedger(store)
    ledger.reserve("call-1", "worker", True)
    ledger.finish(
        "call-1",
        TurnResult(
            TurnStatus.OK, 0, "x", "", (), 1.0, usage=USAGE
        ),
        None,
    )
    with pytest.raises(SafetyStop, match="Token-Grenze erreicht: 60"):
        ledger.reserve("call-2", "worker", True)
