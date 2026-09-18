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
    QuotaMeasurement,
    QuotaStatus,
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
    QuotaBaseline,
    SafetyLimits,
    SafetyStop,
    stagnation_reason,
)
from ki_dev.machine import Limits
from ki_dev.repository_finalization import StaticFinalizer
from ki_dev.run_store import RunStore, RunStoreError
from ki_dev.usage import (
    CounterScope,
    TokenCounts,
    UsageEvent,
    UsageStatus,
)
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

    def measure_quota(self, session_id):
        del session_id
        return QuotaMeasurement(
            QuotaStatus.MEASURED,
            used_percent=0.0,
            resets_at=9_999_999_999,
        )


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


@pytest.mark.parametrize("role", ["build", "review"])
def test_agent_failure_still_records_normalized_usage_event(
    tmp_path, role
):
    """Ein vorgegebenes Fake-Event wird auch im Abbruchpfad verbucht.
    Die Adapterintegration prueft test_turn_usage_integration.py.
    """
    # Dieselben Kategorienwerte wie ``USAGE`` (der Legacy-Nachweis aus
    # demselben Turn): in der echten Anbindung stammen beide aus
    # derselben Rohantwort und duerfen sich nie widersprechen (siehe
    # tests/test_usage_accounting.py,
    # test_claude_call_total_summary_reconciles_with_legacy_usage).
    # ``provider="fake"`` deckt sich mit ``Executor.name`` ("fake" ist
    # in ``PROVIDER_FAMILY_BY_EXECUTOR`` nicht abgebildet und bleibt
    # deshalb sich selbst gleich).
    event = UsageEvent(
        UsageStatus.MEASURED,
        "fake",
        "cli_result",
        CounterScope.CALL_TOTAL,
        cli_version="2.1.272",
        session_id=role,
        tokens=TokenCounts(
            fresh_input=10,
            cache_read=100,
            cache_creation=30,
            output=20,
        ),
    )
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
            usage_event=event,
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
        run.start(_task("guard"), Limits(process_retries=3))

    report = CallLedger(RunStore(tmp_path, "guard")).usage_report()
    assert report.total == event.tokens.total
    recorded = [call for call in report.calls if call.evidence_refs]
    assert len(recorded) == 1
    assert set(recorded[0].gaps) <= {"attribution_missing"}


def test_successful_review_turn_records_usage_event(tmp_path):
    """Ein vorgegebenes Fake-Event wird im Erfolgspfad verbucht.
    Die Adapterintegration prueft test_turn_usage_integration.py.
    """
    event = UsageEvent(
        UsageStatus.MEASURED,
        "fake",
        "cli_result",
        CounterScope.CALL_TOTAL,
        cli_version="2.1.272",
        session_id="review",
        tokens=TokenCounts(
            fresh_input=10,
            cache_read=100,
            cache_creation=30,
            output=20,
        ),
    )
    review_json = json.dumps(
        {
            "run_id": "guard",
            "round_id": 1,
            "action": ReviewAction.PASS.value,
            "detail": "",
            "requirement_ref": None,
        }
    )
    executor = Executor(
        TurnResult(
            TurnStatus.OK,
            0,
            review_json,
            "",
            (),
            1.0,
            usage=USAGE,
            usage_event=event,
        )
    )
    builder = FakeBuilder()
    reviewer = AgentReviewer(executor, "review", "model", Effort.LOW)
    with runtime(tmp_path, builder, reviewer) as run:
        result = run.start(_task("guard"), Limits())

    assert result.status == "passed"
    store = RunStore(tmp_path, "guard")
    ledger = CallLedger(store)
    report = ledger.usage_report()
    assert report.total == event.tokens.total
    recorded = [call for call in report.calls if call.evidence_refs]
    assert len(recorded) == 1
    assert recorded[0].reconciliation == "summary_only"
    assert set(recorded[0].gaps) <= {"attribution_missing"}

    # Beweis, dass diese Gaps tatsaechlich nicht blockieren: eine
    # weitere Reservierung bleibt moeglich.
    ledger.reserve("call-danach", "review", True, "fake")


@pytest.mark.parametrize("failed", [False, True])
def test_reservation_stays_locked_between_record_usage_and_finish(
    tmp_path, monkeypatch, failed
):
    """ki-dev-ablauf-wu0.3 Nachreview: ``finish()`` (das die
    "ungeklaert"-Sperre aus ``reserve()`` loescht) darf erst NACH dem
    Verbrauchsbeleg geschrieben werden -- sonst rutscht eine
    Reservierung in genau diesem Fenster durch, obwohl ein
    PARTIAL-Beleg sie sperren muesste; ein Prozessabbruch dazwischen
    liesse diese Sperrinformation dauerhaft fehlen. Betrifft
    ``LoopRuntime._metered_operation`` in beiden Zweigen (Erfolg und
    Fehlerpfad).
    """
    event = UsageEvent(
        UsageStatus.PARTIAL,
        "fake",
        "cli_result",
        CounterScope.CALL_TOTAL,
        cli_version="0.0.0",
        session_id="build",
        tokens=TokenCounts(
            fresh_input=10,
            cache_read=100,
            cache_creation=30,
            output=20,
        ),
    )
    result = (
        TurnResult(
            TurnStatus.NONZERO_EXIT,
            1,
            "",
            "rate_limit: five_hour",
            (),
            2.0,
            error="session limit",
            usage=USAGE,
            usage_event=event,
        )
        if failed
        else TurnResult(
            TurnStatus.OK,
            0,
            "fertig",
            "",
            (),
            1.0,
            usage=USAGE,
            usage_event=event,
        )
    )
    executor = Executor(result)
    builder = AgentBuildMode(executor, "build", "model", Effort.LOW)
    reviewer = FakeReviewer([ReviewAction.PASS])

    # Fuer jeden ``finish()``-Aufruf festhalten, ob der Verbrauchs-
    # beleg fuer denselben ``call_id`` in diesem Moment bereits auf
    # der Platte steht. Bei richtiger Reihenfolge (Beleg vor
    # ``finish()``) ist das fuer jeden Aufruf, der am Ende ueberhaupt
    # einen Beleg bekommt, immer schon der Fall -- bei der im Befund
    # beschriebenen falschen Reihenfolge (``finish()`` vor dem Beleg)
    # waere es an dieser Stelle noch ``False``.
    entries: list[tuple[str, bool]] = []
    original = CallLedger.finish

    def spy(self, call_id_arg, *args, **kwargs):
        value = original(self, call_id_arg, *args, **kwargs)
        entries.append(
            (call_id_arg, bool(self.store.load_usage(call_id_arg)))
        )
        return value

    monkeypatch.setattr(CallLedger, "finish", spy)

    with runtime(tmp_path, builder, reviewer) as run:
        run.start(_task("guard"), Limits(process_retries=3))

    report = CallLedger(RunStore(tmp_path, "guard")).usage_report()
    recorded_ids = {
        call.call_id for call in report.calls if call.evidence_refs
    }
    assert recorded_ids
    for call_id, had_usage_when_finished in entries:
        if call_id in recorded_ids:
            assert had_usage_when_finished, (
                f"finish() fuer {call_id} lief vor dem "
                "Verbrauchsbeleg -- Sperrinformation kann bei einem "
                "Prozessabbruch dazwischen verloren gehen"
            )


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
            "max_usage_delta_percentage_points": 20.0,
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


def test_quota_baseline_first_measurement_returns_zero_delta(tmp_path):
    store = RunStore(tmp_path, "run-x")
    baseline = QuotaBaseline(store)
    assert baseline.delta_percent("build", 40.0, resets_at=1000) == 0.0


def test_quota_baseline_same_window_returns_growth(tmp_path):
    store = RunStore(tmp_path, "run-x")
    baseline = QuotaBaseline(store)
    baseline.delta_percent("build", 40.0, resets_at=1000)
    assert baseline.delta_percent("build", 55.0, resets_at=1000) == 15.0


def test_quota_baseline_window_rollover_resets_to_zero(tmp_path):
    """Ein anderes ``resets_at`` heisst: das Kontingent hat sich real
    erneuert. Ohne Rollover-Erkennung wuerde ein niedriger neuer
    Messwert gegen eine alte, hohe Basislinie faelschlich als grosser
    negativer oder -- im umgekehrten Fall wie hier -- ein frischer,
    tatsaechlich kleiner Verbrauch faelschlich als grosses Delta
    gegen eine alte, sehr niedrige Basislinie erscheinen."""
    store = RunStore(tmp_path, "run-x")
    baseline = QuotaBaseline(store)
    baseline.delta_percent("build", 1.0, resets_at=1000)
    # Fenster wechselt (anderes resets_at); ohne Reset waere das
    # Delta 15.0 - 1.0 = 14.0 statt der korrekten 0.0 fuer ein
    # frisches Fenster.
    assert baseline.delta_percent("build", 15.0, resets_at=2000) == 0.0


def test_quota_baseline_persists_across_new_instance_same_store(
    tmp_path,
):
    """Die Basislinie ueberlebt Resume/Prozessneustart unveraendert,
    solange das Fenster dasselbe bleibt (kein stiller Reset)."""
    store = RunStore(tmp_path, "run-x")
    QuotaBaseline(store).delta_percent("build", 40.0, resets_at=1000)
    fresh = QuotaBaseline(RunStore(tmp_path, "run-x"))
    assert fresh.delta_percent("build", 48.0, resets_at=1000) == 8.0


def test_quota_baseline_is_independent_per_role(tmp_path):
    store = RunStore(tmp_path, "run-x")
    baseline = QuotaBaseline(store)
    baseline.delta_percent("build", 10.0, resets_at=1000)
    baseline.delta_percent("review", 70.0, resets_at=1000)
    assert baseline.delta_percent("build", 12.0, resets_at=1000) == 2.0
    assert baseline.delta_percent("review", 74.0, resets_at=1000) == 4.0


def test_quota_baseline_rejects_resets_at_regression(tmp_path):
    """Ein resets_at UNTER der gespeicherten Basislinie ist kein
    legitimer neuer Fensterstand (ein echter Rollover erhoeht
    resets_at immer), sondern ein widerspruechlicher Messwert --
    er wird gemeldet, nicht als stiller Reset uebernommen."""
    store = RunStore(tmp_path, "run-x")
    baseline = QuotaBaseline(store)
    baseline.delta_percent("build", 50.0, resets_at=2000)
    with pytest.raises(RunStoreError, match="widerspruechlich"):
        baseline.delta_percent("build", 5.0, resets_at=1000)
