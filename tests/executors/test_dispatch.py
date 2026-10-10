from __future__ import annotations

from pathlib import Path

import pytest

from ki_dev.adapter.executors import (
    Effort,
    TurnResult,
    TurnStatus,
    build_executor,
    cli_transports,
    send_turn,
)
from ki_dev.adapter.executors.claude_cli import ClaudeCliAdapter
from ki_dev.adapter.executors.codex_cli import CodexCliAdapter

from .conftest import FakeRunner


def test_known_transports_are_listed():
    assert set(cli_transports()) == {"claude-cli", "codex-cli"}


@pytest.mark.parametrize(
    ("transport", "cls"),
    [("claude-cli", ClaudeCliAdapter), ("codex-cli", CodexCliAdapter)],
)
def test_build_executor_by_transport(transport, cls):
    assert isinstance(build_executor(transport), cls)


def test_unknown_transport_is_rejected():
    with pytest.raises(ValueError, match="Unbekannter transport"):
        build_executor("gemini")


def test_send_turn_dispatches_by_name():
    runner = FakeRunner()
    result = send_turn(
        "codex-cli",
        session="01J-sess",
        message="mach weiter",
        model="gpt-5-codex",
        effort=Effort.HIGH,
        workdir=Path("/work"),
        runner=runner,
    )
    assert result is runner.result
    assert runner.argv[0] == "codex"
    assert runner.value_after("resume") == "01J-sess"
    assert runner.value_after("-c") == "model_reasoning_effort=high"
    assert runner.stdin == "mach weiter"


def test_send_turn_reports_runner_failure():
    failed = TurnResult(
        status=TurnStatus.START_ERROR,
        exit_code=None,
        stdout="",
        stderr="",
        argv=(),
        duration_s=0.0,
        error="Prozessstart fehlgeschlagen: claude fehlt",
    )
    result = send_turn(
        "claude-cli",
        session="sess-x",
        message="hallo",
        model="claude-sonnet-5",
        effort=Effort.LOW,
        workdir=Path("/work"),
        runner=FakeRunner(failed),
    )
    assert result.status is TurnStatus.START_ERROR
