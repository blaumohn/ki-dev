"""Neue Sitzungen und Dateizugriff je Turn (ohne Anbieterzugang).

Ohne ``session_id`` legt die CLI eine Sitzung an und nennt ihre ID in
der Ausgabe; ``access`` wird zu den Rechten der CLI.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from ki_dev.adapter.executors import (
    Access,
    ClaudeCliAdapter,
    CodexCliAdapter,
    Effort,
    TurnRequest,
    TurnResult,
    TurnStatus,
)
from ki_dev.adapter.executors.contract import QuotaStatus, TurnBudget

from .conftest import FakeRunner

THREAD = "019a0000-0000-7000-8000-000000000001"


def _request(**over: object) -> TurnRequest:
    base = {
        "session_id": None,
        "message": "auftrag",
        "model": "m",
        "effort": Effort.LOW,
        "workdir": Path("/work"),
        "budget": TurnBudget(),
    }
    base.update(over)
    return TurnRequest(**base)  # type: ignore[arg-type]


def _ok(stdout: str) -> TurnResult:
    return TurnResult(TurnStatus.OK, 0, stdout, "", (), 1.0)


def _codex_events(*, started: bool = True) -> str:
    events = [
        {"type": "thread.started", "thread_id": THREAD},
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "fertig"},
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 10,
                "cached_input_tokens": 0,
                "output_tokens": 5,
            },
        },
    ]
    shown = events if started else events[1:]
    return "\n".join(json.dumps(event) for event in shown)


def _claude_result(**over: object) -> str:
    value = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "fertig",
        "num_turns": 1,
        "total_cost_usd": 0.01,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        },
        "permission_denials": [],
        "session_id": "b3f1c0de-0000-4000-8000-000000000002",
    }
    value.update(over)
    return json.dumps(value)


def test_codex_new_session_runs_exec_without_resume():
    argv = CodexCliAdapter().build_argv(_request())
    assert argv[0] == "exec"
    assert "resume" not in argv
    assert argv[-2:] == ["--json", "-"]


def test_codex_new_session_reports_thread_id():
    runner = FakeRunner(_ok(_codex_events()))
    result = CodexCliAdapter(runner=runner).send_turn(_request())
    assert result.ok
    assert result.session_id == THREAD
    assert result.usage_event.session_id == THREAD


def test_codex_named_session_is_reported_unchanged():
    runner = FakeRunner(_ok(_codex_events(started=False)))
    request = _request(session_id="01J-codex-session")
    result = CodexCliAdapter(runner=runner).send_turn(request)
    assert result.ok
    assert result.session_id == "01J-codex-session"


def test_codex_new_session_without_thread_id_fails_visibly():
    runner = FakeRunner(_ok(_codex_events(started=False)))
    result = CodexCliAdapter(runner=runner).send_turn(_request())
    assert result.status is TurnStatus.NONZERO_EXIT
    assert "thread.started" in result.error


def test_codex_new_session_needs_json_output():
    with pytest.raises(ValueError, match="TurnBudget"):
        CodexCliAdapter(runner=FakeRunner()).send_turn(
            _request(budget=None)
        )


@pytest.mark.parametrize(
    ("access", "sandbox"),
    [
        (Access.READ, 'sandbox_mode="read-only"'),
        (Access.WRITE, 'sandbox_mode="workspace-write"'),
    ],
)
def test_codex_access_becomes_sandbox(access, sandbox):
    for session_id in (None, "01J-codex-session"):
        argv = CodexCliAdapter().build_argv(
            _request(session_id=session_id, access=access)
        )
        assert argv[argv.index(sandbox) - 1] == "-c"


def test_codex_without_access_keeps_cli_setting():
    argv = CodexCliAdapter().build_argv(_request())
    assert not any(arg.startswith("sandbox_mode") for arg in argv)


def test_claude_new_session_chooses_a_uuid():
    argv = ClaudeCliAdapter().build_argv(_request())
    assert "--resume" not in argv
    UUID(argv[argv.index("--session-id") + 1])


def test_claude_new_session_reports_id_from_result_event():
    runner = FakeRunner(_ok(_claude_result()))
    result = ClaudeCliAdapter(runner=runner).send_turn(_request())
    assert result.ok
    assert result.session_id == "b3f1c0de-0000-4000-8000-000000000002"


def test_claude_new_session_without_reported_id_fails_visibly():
    runner = FakeRunner(_ok(_claude_result(session_id=None)))
    result = ClaudeCliAdapter(runner=runner).send_turn(_request())
    assert result.status is TurnStatus.NONZERO_EXIT
    assert "Sitzungs-ID" in result.error


def test_claude_new_session_needs_stream_output():
    with pytest.raises(ValueError, match="TurnBudget"):
        ClaudeCliAdapter(runner=FakeRunner()).send_turn(
            _request(budget=None)
        )


def test_claude_quota_of_a_new_session_is_pending():
    measurement = ClaudeCliAdapter().measure_quota(None)
    assert measurement.status is QuotaStatus.PENDING


@pytest.mark.parametrize(
    ("access", "args"),
    [
        (Access.READ, ["--tools", "Read,Grep,Glob"]),
        (Access.WRITE, ["--permission-mode", "acceptEdits"]),
    ],
)
def test_claude_access_becomes_tools_or_permission_mode(access, args):
    argv = ClaudeCliAdapter().build_argv(_request(access=access))
    start = argv.index(args[0])
    assert argv[start : start + 2] == args


def test_claude_without_access_keeps_cli_setting():
    argv = ClaudeCliAdapter().build_argv(
        replace(_request(), session_id="s")
    )
    assert "--tools" not in argv
    assert "--permission-mode" not in argv


@pytest.mark.parametrize(
    "adapter_type", [ClaudeCliAdapter, CodexCliAdapter]
)
def test_failed_new_session_reports_only_the_failure(adapter_type):
    """Ein gescheiterter Start nennt seinen Grund, keine fehlende ID."""
    failed = TurnResult(
        TurnStatus.START_ERROR, None, "", "", (), 0.0,
        error="CLI nicht auffindbar",
    )
    adapter = adapter_type(runner=FakeRunner(failed))
    result = adapter.send_turn(_request())
    assert result.status is TurnStatus.START_ERROR
    assert "CLI nicht auffindbar" in result.error
    assert "Sitzungs-ID" not in result.error
    assert result.session_id is None
