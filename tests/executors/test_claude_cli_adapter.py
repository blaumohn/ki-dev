from __future__ import annotations

from pathlib import Path

import pytest

from ki_dev.adapter.executors import (
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
        "workdir": Path("/work"),
    }
    base.update(over)
    return TurnRequest(**base)  # type: ignore[arg-type]


def test_send_turn_binds_child_process_to_task_workdir():
    """CliAdapter.send_turn() (base.py, gemeinsam fuer alle Adapter)
    muss den Kindprozess technisch an ``request.workdir`` binden;
    eine Pfadangabe allein im Prompt reicht dafuer nicht (p0h.3)."""
    runner = FakeRunner()
    ClaudeCliAdapter(runner=runner).send_turn(
        _request(workdir=Path("/worktree/x"))
    )
    assert runner.last_kwargs["cwd"] == Path("/worktree/x")


def test_send_turn_overlays_bound_env_on_inherited_environment():
    runner = FakeRunner()
    ClaudeCliAdapter(runner=runner).send_turn(
        _request(env={"PYTHONPATH": "/worktree/x/src"})
    )
    env = runner.last_kwargs["env"]
    assert env["PYTHONPATH"] == "/worktree/x/src"
    assert "PATH" in env  # geerbte Umgebung bleibt sonst erhalten


def test_send_turn_passes_no_env_override_without_bound_values():
    runner = FakeRunner()
    ClaudeCliAdapter(runner=runner).send_turn(_request())
    assert runner.last_kwargs["env"] is None


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
