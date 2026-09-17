from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from ki_dev.executors import ClaudeCliAdapter, CodexCliAdapter, Effort
from ki_dev.executors.contract import (
    ContextStatus,
    TurnBudget,
    TurnRequest,
    TurnResult,
    TurnStatus,
)
from ki_dev.executors.metering import (
    claude_context_tokens,
    claude_result,
    codex_result,
)

from .conftest import FakeRunner


def _result(stdout, **kwargs):
    return replace(
        TurnResult(TurnStatus.OK, 0, stdout, "", (), 1.0), **kwargs
    )


def _claude(**kwargs):
    value = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "fertig",
        "num_turns": 3,
        "total_cost_usd": 0.2,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 20,
            "cache_read_input_tokens": 500,
            "cache_creation_input_tokens": 30,
        },
        "permission_denials": [],
    }
    value.update(kwargs)
    return json.dumps(value)


def test_claude_usage_and_answer_are_separate():
    result = claude_result(_result(_claude()))
    assert result.ok
    assert result.stdout == "fertig"
    assert result.usage == {
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_read_input_tokens": 500,
        "cache_creation_input_tokens": 30,
        "num_turns": 3,
        "cost_usd": 0.2,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"subtype": "error_max_turns", "is_error": True},
        {"subtype": "error_max_budget_usd", "is_error": True},
        {"result": "You've hit your session limit", "is_error": True},
        {"permission_denials": [{"tool_name": "Read"}]},
    ],
)
def test_zero_exit_is_not_success_on_provider_blocker(changes):
    result = claude_result(_result(_claude(**changes)))
    assert not result.ok
    assert result.usage["cost_usd"] == 0.2
    assert result.error


@pytest.mark.parametrize(
    "stdout",
    [
        "fertig",
        "[]",
        _claude(usage=None),
        _claude(total_cost_usd=float("nan")),
        _claude(num_turns=True),
    ],
)
def test_missing_or_invalid_claude_usage_is_a_stop(stdout):
    assert not claude_result(_result(stdout)).ok


def test_provider_failure_preserves_diagnostic():
    result = claude_result(
        _result(
            "You've hit your session limit",
            status=TurnStatus.NONZERO_EXIT,
            exit_code=1,
            error="CLI endete mit Exitstatus 1",
        )
    )
    assert "session limit" in result.error


def _session(root, usage):
    path = root / "workspace" / "session.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "model": "claude",
                    "usage": usage,
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "model": "<synthetic>",
                    "usage": {"input_tokens": 0},
                },
            }
        )
        + "\n"
    )


def test_context_preflight_counts_cached_input_and_skips_synthetic(
    tmp_path,
):
    _session(
        tmp_path,
        {
            "input_tokens": 2,
            "cache_creation_input_tokens": 100,
            "cache_read_input_tokens": 90_000,
        },
    )
    assert claude_context_tokens("session", tmp_path) == 90_102


def _request():
    return TurnRequest(
        "session",
        "auftrag",
        "model",
        Effort.MEDIUM,
        Path("/work"),
        budget=TurnBudget(),
    )


def test_claude_measure_context_reports_real_value(monkeypatch):
    """Die Kontextvorpruefung ist keine Aufgabe des Adapters mehr
    (ki-dev-ablauf-agu): ``measure_context`` liefert nur den
    Messwert, ohne den naechsten Aufruf selbst zu verhindern."""
    monkeypatch.setattr(
        "ki_dev.executors.claude_cli.claude_context_tokens",
        lambda *_: 90_000,
    )
    measurement = ClaudeCliAdapter().measure_context("session")
    assert measurement.status is ContextStatus.MEASURED
    assert measurement.tokens == 90_000


def test_claude_measure_context_reports_unavailable_explicitly(
    monkeypatch,
):
    def _raise(*_args):
        raise ValueError("Claude-Sitzung hat keinen Verbrauchsnachweis")

    monkeypatch.setattr(
        "ki_dev.executors.claude_cli.claude_context_tokens", _raise
    )
    measurement = ClaudeCliAdapter().measure_context("session")
    assert measurement.status is ContextStatus.UNAVAILABLE
    assert measurement.tokens is None
    assert "Verbrauchsnachweis" in measurement.detail


def test_codex_measure_context_is_explicitly_unsupported():
    measurement = CodexCliAdapter().measure_context("session")
    assert measurement.status is ContextStatus.UNSUPPORTED
    assert measurement.tokens is None


def test_bounded_claude_uses_native_limits_and_timeout():
    runner = FakeRunner(_result(_claude()))
    result = ClaudeCliAdapter(runner=runner).send_turn(_request())
    assert result.ok
    assert runner.value_after("--output-format") == "json"
    assert runner.value_after("--max-turns") == "12"
    assert runner.value_after("--max-budget-usd") == "1.0"
    assert runner.calls[0][2] == 180


def _codex():
    return "\n".join(
        json.dumps(event)
        for event in [
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": "pruefe noch",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": '{"action":"PASS"}',
                },
            },
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 1000,
                    "cached_input_tokens": 900,
                    "output_tokens": 50,
                },
            },
        ]
    )


def test_codex_usage_does_not_double_count_cached_input():
    runner = FakeRunner(_result(_codex()))
    result = CodexCliAdapter(runner=runner).send_turn(_request())
    assert result.stdout == '{"action":"PASS"}'
    assert result.usage["input_tokens"] == 100
    assert result.usage["cache_read_input_tokens"] == 900
    assert "--json" in runner.argv
    assert runner.calls[0][2] == 180


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        "{}",
        '{"type":"turn.failed","error":{"message":"quota"}}',
    ],
)
def test_codex_missing_or_failed_turn_never_passes(text):
    assert not codex_result(_result(text)).ok


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_turns": 0},
        {"max_turns": True},
        {"max_budget_usd": float("nan")},
        {"timeout_s": float("inf")},
        {"max_context_tokens": -1},
    ],
)
def test_invalid_budgets_rejected(kwargs):
    with pytest.raises(ValueError):
        TurnBudget(**kwargs)
