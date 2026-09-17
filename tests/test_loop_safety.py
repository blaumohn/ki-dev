from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import pytest

from ki_dev.executors import Effort
from ki_dev.executors.contract import (
    ContextMeasurement,
    ContextStatus,
    TurnResult,
    TurnStatus,
)
from ki_dev.loop import (
    AgentBuildMode,
    AgentReviewer,
    LoopTask,
    ReviewAction,
)
from ki_dev.loop_cli import LoopConfigError, _role, start_from_config
from ki_dev.loop_runtime import (
    LoopResumeError,
    LoopRuntime,
    StaticEvidenceCollector,
)
from ki_dev.loop_safety import (
    CallLedger,
    SafetyLimits,
    SafetyStop,
    stagnation_reason,
)
from ki_dev.machine import Limits
from ki_dev.repository_finalization import StaticFinalizer
from ki_dev.run_store import RunStore
from tests.test_loop_runtime import (
    FakeBuilder,
    FakeReviewer,
    _context,
    _task,
)

USAGE = {
    "input_tokens": 10,
    "output_tokens": 20,
    "cache_read_input_tokens": 100,
    "cache_creation_input_tokens": 30,
    "cost_usd": 0.2,
}


class Executor:
    name = "fake"

    def __init__(self, result):
        self.result = result
        self.calls = 0

    def send_turn(self, request):
        self.calls += 1
        assert request.budget is not None
        return self.result

    def measure_context(self, session_id):
        del session_id
        return ContextMeasurement(ContextStatus.UNSUPPORTED)


def runtime(tmp_path, builder, reviewer, **kwargs):
    return LoopRuntime(
        RunStore(tmp_path, "guard"),
        builder,
        reviewer,
        StaticEvidenceCollector(
            tuple(_context(i) for i in range(1, 6))
        ),
        StaticFinalizer(),
        **kwargs,
    )


@pytest.mark.parametrize("role", ["build", "review"])
def test_agent_failure_pauses_immediately_and_keeps_usage(
    tmp_path, role
):
    executor = Executor(
        TurnResult(
            TurnStatus.NONZERO_EXIT,
            1,
            "",
            "rate_limit: five_hour",
            (),
            2.0,
            error="session limit",
            usage=USAGE,
        )
    )
    builder = (
        AgentBuildMode(executor, "build", "model", Effort.LOW)
        if role == "build"
        else FakeBuilder()
    )
    reviewer = (
        AgentReviewer(executor, "review", "model", Effort.LOW)
        if role == "review"
        else FakeReviewer([ReviewAction.PASS])
    )
    with runtime(tmp_path, builder, reviewer) as run:
        result = run.start(_task("guard"), Limits(process_retries=3))
    assert result.status == "paused_interactive"
    assert "session limit" in result.detail
    assert "five_hour" in result.detail
    assert executor.calls == 1
    docs = [
        json.loads(p.read_text())
        for p in (tmp_path / "guard/calls").glob("*-result.json")
    ]
    assert any(d["usage"] == USAGE for d in docs)
    with (
        runtime(tmp_path, builder, reviewer) as run,
        pytest.raises(LoopResumeError, match="Antwort"),
    ):
        run.resume()
    assert executor.calls == 1


def test_two_failed_corrections_stop_before_fourth_build(tmp_path):
    builder = FakeBuilder()
    reviewer = FakeReviewer([ReviewAction.CHANGES] * 4)
    with runtime(tmp_path, builder, reviewer) as run:
        result = run.start(_task("guard"), Limits(changes_rounds=5))
    assert result.status == "paused_interactive"
    assert "Korrekturen" in result.detail
    assert builder.calls == reviewer.calls == 3


def test_stagnant_same_reference_stops_before_next_build(tmp_path):
    builder = FakeBuilder()
    reviewer = FakeReviewer([ReviewAction.CHANGES] * 5)
    with runtime(
        tmp_path,
        builder,
        reviewer,
        safety_limits=SafetyLimits(
            max_failed_corrections=10, max_stagnant_changes=3
        ),
    ) as run:
        result = run.start(_task("guard"), Limits(changes_rounds=5))
    assert result.status == "paused_interactive"
    assert "Stillstand" in result.detail
    assert "AC1" in result.detail
    # Drei CHANGES-Runden in Folge an derselben Referenz halten vor
    # dem vierten Bauaufruf an, unabhaengig von max_failed_corrections.
    assert builder.calls == reviewer.calls == 3
    handoffs = list((tmp_path / "guard" / "handoff").glob("*.json"))
    assert len(handoffs) == 1
    handoff = json.loads(handoffs[0].read_text())
    assert handoff["open_requirement_ref"] == "AC1"
    assert handoff["needed_decision"] in result.detail
    assert handoff["acceptance_criteria"] == ["Kriterium 1"]


def test_changing_reference_is_not_treated_as_stagnation(tmp_path):
    task = LoopTask(
        "guard",
        "Auftrag",
        ("bd:jbr.2",),
        Path("/work"),
        "write",
        acceptance_criteria=("Kriterium 1", "Kriterium 2"),
    )
    builder = FakeBuilder()
    reviewer = FakeReviewer(
        [
            (ReviewAction.CHANGES, "AC1"),
            (ReviewAction.CHANGES, "AC2"),
            (ReviewAction.CHANGES, "AC1"),
            ReviewAction.PASS,
        ]
    )
    with runtime(
        tmp_path,
        builder,
        reviewer,
        safety_limits=SafetyLimits(
            max_agent_calls=20,
            max_failed_corrections=10,
            max_stagnant_changes=2,
        ),
    ) as run:
        result = run.start(task, Limits(changes_rounds=5))
    assert result.status == "passed"
    assert builder.calls == reviewer.calls == 4


def test_stagnation_reason_persists_across_fresh_store_instances(
    tmp_path,
):
    """Der Stillstand wird aus persistierten Nachrichten neu berechnet,
    nicht aus Prozessspeicher; ein Neustart/Sitzungswechsel setzt die
    Serie deshalb nicht zurueck.

    Der Aufrufer persistiert die aktuelle Entscheidung immer VOR dem
    Aufruf von ``stagnation_reason`` (siehe dessen Docstring); die
    dritte gleichlautende Nachricht hier steht fuer genau diese schon
    gespeicherte aktuelle Entscheidung.
    """
    store = RunStore(tmp_path, "run-x")
    for round_id in (1, 2, 3):
        store.write_message(
            f"r{round_id:04d}-review-a0000",
            {
                "run_id": "run-x",
                "round_id": round_id,
                "action": "CHANGES",
                "detail": "x",
                "requirement_ref": "AC1",
            },
        )

    fresh_store = RunStore(tmp_path, "run-x")
    reason = stagnation_reason(
        fresh_store, action="CHANGES", requirement_ref="AC1", limit=3
    )
    assert reason is not None
    assert "AC1" in reason
    assert "seit 3 Korrekturrunden in Folge verletzt" in reason

    below_limit = stagnation_reason(
        fresh_store, action="CHANGES", requirement_ref="AC1", limit=4
    )
    assert below_limit is None


def test_stagnation_reason_ignores_non_matching_history(tmp_path):
    store = RunStore(tmp_path, "run-y")
    store.write_message(
        "r0001-review-a0000",
        {
            "run_id": "run-y",
            "round_id": 1,
            "action": "CHANGES",
            "detail": "x",
            "requirement_ref": "AC2",
        },
    )
    store.write_message(
        "r0002-review-a0000",
        {
            "run_id": "run-y",
            "round_id": 2,
            "action": "CHANGES",
            "detail": "x",
            "requirement_ref": "AC1",
        },
    )
    assert (
        stagnation_reason(
            store, action="CHANGES", requirement_ref="AC1", limit=2
        )
        is None
    )
    assert (
        stagnation_reason(
            store, action="PASS", requirement_ref=None, limit=1
        )
        is None
    )


def test_stagnation_reason_reports_recorded_consumption(tmp_path):
    store = RunStore(tmp_path, "run-z")
    store.write_message(
        "r0001-review-a0000",
        {
            "run_id": "run-z",
            "round_id": 1,
            "action": "CHANGES",
            "detail": "x",
            "requirement_ref": "AC1",
        },
    )
    (store.run_dir / "calls").mkdir(parents=True, exist_ok=True)
    store._write_once(
        store.run_dir / "calls" / "call-1-result.json",
        {"status": "ok", "usage": {**USAGE}},
    )
    store.write_message(
        "r0002-review-a0000",
        {
            "run_id": "run-z",
            "round_id": 2,
            "action": "CHANGES",
            "detail": "x",
            "requirement_ref": "AC1",
        },
    )

    reason = stagnation_reason(
        store, action="CHANGES", requirement_ref="AC1", limit=2
    )

    assert reason is not None
    assert "160" in reason  # Summe aller Tokenarten aus USAGE
    assert "0.2" in reason  # cost_usd


def test_call_limit_survives_restart_and_answer(tmp_path):
    builder = FakeBuilder()
    reviewer = FakeReviewer([ReviewAction.CHANGES])
    with runtime(
        tmp_path,
        builder,
        reviewer,
        safety_limits=SafetyLimits(max_agent_calls=2),
    ) as run:
        result = run.start(_task("guard"), Limits())
    assert result.status == "paused_interactive"
    with runtime(tmp_path, builder, reviewer) as run:
        result = run.resume("weiter")
    assert result.status == "paused_interactive"
    assert builder.calls == reviewer.calls == 1
    assert "Aufrufgrenze" in result.detail


@pytest.mark.parametrize(
    "limits,usage,match",
    [
        (SafetyLimits(max_total_tokens=100), USAGE, "Token-Grenze"),
        (SafetyLimits(max_claude_cost_usd=0.1), USAGE, "Kostengrenze"),
        (SafetyLimits(), None, "unbekannt"),
    ],
)
def test_budget_blocks_next_paid_call(tmp_path, limits, usage, match):
    executor = Executor(
        TurnResult(TurnStatus.OK, 0, "Bau", "", (), 1.0, usage=usage)
    )
    builder = AgentBuildMode(executor, "build", "model", Effort.LOW)
    reviewer = FakeReviewer([ReviewAction.PASS])
    with runtime(
        tmp_path, builder, reviewer, safety_limits=limits
    ) as run:
        result = run.start(_task("guard"), Limits())
    assert result.status == "paused_interactive"
    assert match in result.detail
    assert executor.calls == 1
    assert reviewer.calls == 0


def test_legacy_run_cannot_silently_start_paid_work(tmp_path):
    store = RunStore(tmp_path, "old")
    store.initialize({"configuration": {}})
    with pytest.raises(SafetyStop, match="Altlauf"):
        CallLedger(store).reserve("call-1", "build", True)
    assert not (store.run_dir / "calls").exists()


def test_started_call_without_result_is_not_free_after_restart(
    tmp_path,
):
    store = RunStore(tmp_path, "guard")
    store.initialize({"safety_limits": asdict(SafetyLimits())})
    CallLedger(store).reserve("call-1", "build", True)
    with pytest.raises(SafetyStop, match="ungeklaert"):
        CallLedger(store).reserve("call-2", "build", True)


def test_concurrent_reservations_cannot_bypass_limit(tmp_path):
    store = RunStore(tmp_path, "guard")
    store.initialize({"safety_limits": asdict(SafetyLimits())})

    def reserve(number):
        try:
            CallLedger(store).reserve(f"call-{number}", "build", True)
            return True
        except SafetyStop:
            return False

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(reserve, range(2)))
    assert sorted(outcomes) == [False, True]


def test_reconcile_real_call_requires_usage(tmp_path):
    store = RunStore(tmp_path, "guard")
    store.initialize({"safety_limits": asdict(SafetyLimits())})
    ledger = CallLedger(store)
    ledger.reserve("call-1", "build", True)
    with pytest.raises(SafetyStop, match="Verbrauchsnachweis"):
        ledger.reconcile("call-1", {"summary": "fertig"})
    ledger.reconcile("call-1", {"summary": "fertig", "usage": USAGE})
    ledger.reserve("call-2", "review", True)


def test_permission_error_is_not_retried(tmp_path):
    class BlockedBuilder(FakeBuilder):
        def build(self, request):
            del request
            self.calls += 1
            raise PermissionError("Zugriff verweigert")

    builder = BlockedBuilder()
    with runtime(tmp_path, builder, FakeReviewer([])) as run:
        result = run.start(_task("guard"), Limits())
    assert result.status == "paused_interactive"
    assert "Zugriff verweigert" in result.detail
    assert builder.calls == 1


def test_start_pins_effective_role_budgets(monkeypatch, tmp_path):
    path = tmp_path / "loop.json"
    path.write_text(
        json.dumps(
            {
                "task": "Auftrag",
                "acceptance_criteria": ["Kriterium 1"],
                "workdir": str(tmp_path),
                "access_profile": "write",
                "build": {},
                "review": {},
            }
        )
    )
    seen = {}

    class Runtime:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def start(self, task, limits, *, manifest_extra):
            del task, limits
            seen.update(manifest_extra)

    monkeypatch.setattr(
        "ki_dev.loop_cli._runtime", lambda *_: Runtime()
    )
    start_from_config(path, run_id="pin", runs_dir=tmp_path)
    for role in ("build", "review"):
        assert seen["configuration"][role]["budget"] == {
            "max_turns": 12,
            "max_budget_usd": 1.0,
            "max_context_tokens": 80_000,
            "timeout_s": 180.0,
        }


@pytest.mark.parametrize(
    "override",
    [
        {"timeout_s": float("nan")},
        {"timeout_s": 0},
        {"budget": {"max_turns": 0}},
        {"budget": {"typo": 1}},
    ],
)
def test_role_configuration_cannot_disable_bounds(override):
    with pytest.raises(LoopConfigError):
        _role(
            {
                "executor": "claude",
                "model": "model",
                "session_id": "session",
                "effort": "low",
                **override,
            }
        )
