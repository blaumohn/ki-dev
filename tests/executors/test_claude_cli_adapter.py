from __future__ import annotations

import pytest

from ki_dev.executors import (
    ClaudeCliAdapter,
    Effort,
    TurnRequest,
    TurnResult,
    TurnStatus,
)

from .conftest import FakeRunner


def _request(**over: object) -> TurnRequest:
    base = {
        "session_id": "sess-abc",
        "message": "bitte weitermachen",
        "model": "claude-sonnet-5",
        "effort": Effort.HIGH,
    }
    base.update(over)
    return TurnRequest(**base)  # type: ignore[arg-type]


def test_argv_starts_with_claude_binary():
    runner = FakeRunner()
    ClaudeCliAdapter(runner=runner).send_turn(_request())
    assert runner.argv[0] == "claude"
    assert "--print" in runner.argv


def test_session_and_model_translated():
    runner = FakeRunner()
    ClaudeCliAdapter(runner=runner).send_turn(_request())
    assert runner.value_after("--resume") == "sess-abc"
    assert runner.value_after("--model") == "claude-sonnet-5"


@pytest.mark.parametrize(
    "effort",
    [Effort.LOW, Effort.MEDIUM, Effort.HIGH],
)
def test_effort_uses_native_flag(effort):
    runner = FakeRunner()
    ClaudeCliAdapter(runner=runner).send_turn(_request(effort=effort))
    assert runner.value_after("--effort") == effort.value


def test_message_goes_to_stdin():
    runner = FakeRunner()
    ClaudeCliAdapter(runner=runner).send_turn(_request())
    assert runner.stdin == "bitte weitermachen"
    assert "bitte weitermachen" not in runner.argv


def test_executable_and_timeout_forwarded():
    runner = FakeRunner()
    adapter = ClaudeCliAdapter(
        executable="/opt/claude",
        timeout_s=12.5,
        runner=runner,
    )
    adapter.send_turn(_request())
    assert runner.argv[0] == "/opt/claude"
    assert runner.calls[-1][2] == 12.5


def test_runner_result_passed_through():
    timeout = TurnResult(
        status=TurnStatus.TIMEOUT,
        exit_code=None,
        stdout="teil",
        stderr="",
        argv=(),
        duration_s=1.0,
        error="Zeitueberschreitung",
    )
    runner = FakeRunner(timeout)
    result = ClaudeCliAdapter(runner=runner).send_turn(_request())
    assert result is timeout
    assert result.status is TurnStatus.TIMEOUT
