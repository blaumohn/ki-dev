"""wu0.3/AC6: Offline-CLI -> Adapter -> Agent -> persistierte Bilanz.

Der gepruefte Turn nutzt einen echten Adapter mit lokaler Fake-CLI.
Kontext-/Kontingentmessung und die Gegenrolle sind Doubles.
UsageEvent, Normalisierung und Ledger werden nicht vorgegeben.
"""

from __future__ import annotations

import json
from dataclasses import asdict, replace

import pytest

from ki_dev.adapter.agent import (
    AgentReviewer,
    AgentWorker,
)
from ki_dev.adapter.executors import (
    ClaudeCliAdapter,
    CodexCliAdapter,
    Effort,
)
from ki_dev.adapter.executors.contract import (
    ContextMeasurement,
    ContextStatus,
    QuotaMeasurement,
    QuotaStatus,
)
from ki_dev.run_store import RunStore
from ki_dev.runner.machine import Limits
from ki_dev.runner.safety import CallLedger
from ki_dev.usage import CounterScope, TokenCounts, UsageStatus
from tests.executors.usage_fakes import write_usage_cli
from tests.test_runner_runtime import FakeReviewer, FakeWorker, _task
from tests.test_runner_safety import runtime


@pytest.mark.parametrize(
    ("provider", "adapter_type", "expected_tokens"),
    [
        ("claude", ClaudeCliAdapter, TokenCounts(10, 500, 30, 20)),
        ("codex", CodexCliAdapter, TokenCounts(100, 900, 0, 50)),
    ],
    ids=["claude", "codex"],
)
@pytest.mark.parametrize("role", ["worker", "review"])
@pytest.mark.parametrize("failed", [False, True])
def test_cli_turn_records_usage_once_through_agent_and_ledger(
    tmp_path,
    monkeypatch,
    provider,
    adapter_type,
    expected_tokens,
    role,
    failed,
):
    answer = (
        "fertig"
        if role == "worker"
        else json.dumps({
            "run_id": "guard",
            "round_id": 1,
            "event": "PASS",
            "detail": "",
            "requirement_ref": None,
        })
    )
    if provider == "claude":
        output = json.dumps({
            "type": "result",
            "subtype": "error_max_turns" if failed else "success",
            "is_error": failed,
            "result": answer,
            "num_turns": 3,
            "total_cost_usd": 0.2,
            "permission_denials": [],
            "usage": {
                "input_tokens": 10,
                "cache_read_input_tokens": 500,
                "cache_creation_input_tokens": 30,
                "output_tokens": 20,
            },
        })
    else:
        output = "\n".join(json.dumps(event) for event in [
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": answer},
            },
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 1000,
                    "cached_input_tokens": 900,
                    "output_tokens": 50,
                },
            },
        ])
    executable, trace = write_usage_cli(
        tmp_path,
        provider,
        adapter_type.cli_version_pin,
        output,
        exit_code=7 if failed else 0,
    )
    adapter = adapter_type(executable=str(executable))
    # Kein Zugriff auf echte Sitzungsdateien oder Kontingente.
    monkeypatch.setattr(
        adapter,
        "measure_context",
        lambda _session: ContextMeasurement(
            ContextStatus.UNSUPPORTED
        ),
    )
    monkeypatch.setattr(
        adapter,
        "measure_quota",
        lambda _session: QuotaMeasurement(
            QuotaStatus.MEASURED,
            used_percent=0.0,
            resets_at=9_999_999_999,
        ),
    )
    worker = (
        AgentWorker(adapter, "worker", "model", Effort.LOW)
        if role == "worker"
        else FakeWorker()
    )
    reviewer = (
        AgentReviewer(adapter, "review", "model", Effort.LOW)
        if role == "review"
        else FakeReviewer(["PASS"])
    )
    task = replace(_task("guard"), workdir=tmp_path)
    with runtime(tmp_path, worker, reviewer) as run:
        result = run.start(task, Limits(process_retries=3))

    assert result.status == (
        "paused_interactive" if failed else "passed"
    )
    assert trace.read_text().splitlines().count("turn") == 1
    store = RunStore(tmp_path, "guard")
    report = CallLedger(store).usage_report()
    assert report.total == expected_tokens.total
    recorded = [call for call in report.calls if call.evidence_refs]
    assert len(recorded) == 1
    call = recorded[0]
    expected_counts = {
        "fresh_input": expected_tokens.fresh_input,
        "cache_read": expected_tokens.cache_read,
        "cache_creation": expected_tokens.cache_creation,
        "output": expected_tokens.output,
    }
    assert call.counts == expected_counts
    assert call.reconciliation == "summary_only"
    assert set(call.gaps) <= {"attribution_missing"}
    assert call.attribution is not None
    assert call.attribution.role == role
    assert call.attribution.session_id == role
    assert call.status == ("nonzero_exit" if failed else "ok")

    records = store.load_usage(call.call_id)
    assert len(records) == 1
    record = records[0]
    assert record["summary"] is True
    event = record["event"]
    assert event["tokens"] == asdict(expected_tokens)
    assert event["provider"] == provider
    assert event["session_id"] == role
    assert event["cli_version"] == adapter_type.cli_version_pin
    assert event["status"] == UsageStatus.MEASURED.value
    assert event["counter_scope"] == CounterScope.CALL_TOTAL.value
    assert event["source"] == (
        "cli_result" if provider == "claude" else "cli_turn_completed"
    )
    assert call.evidence_refs == (record["evidence_ref"],)

    # Erneutes Lesen aus einem neuen Ledger zaehlt nichts doppelt.
    reopened = CallLedger(RunStore(tmp_path, "guard"))
    assert reopened.usage_report() == report
    reopened.reserve("after-turn", role, True, adapter.name)
