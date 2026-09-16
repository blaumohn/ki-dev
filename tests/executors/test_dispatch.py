from __future__ import annotations

from pathlib import Path

import pytest

from ki_dev.executors import (
    Effort,
    TurnResult,
    TurnStatus,
    available_executors,
    build_executor,
    send_turn,
)
from ki_dev.executors.claude_cli import ClaudeCliAdapter
from ki_dev.executors.codex_cli import CodexCliAdapter

from .conftest import FakeRunner


def test_known_executors_are_listed():
    assert set(available_executors()) == {"claude", "codex"}


@pytest.mark.parametrize(
    ("executor", "cls"),
    [("claude", ClaudeCliAdapter), ("codex", CodexCliAdapter)],
)
def test_build_executor_by_name(executor, cls):
    assert isinstance(build_executor(executor), cls)


def test_unknown_executor_is_rejected():
    with pytest.raises(ValueError, match="Unbekannter executor"):
        build_executor("gemini")


def test_send_turn_dispatches_by_name():
    runner = FakeRunner()
    result = send_turn(
        "codex",
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
        "claude",
        session="sess-x",
        message="hallo",
        model="claude-sonnet-5",
        effort=Effort.LOW,
        workdir=Path("/work"),
        runner=FakeRunner(failed),
    )
    assert result.status is TurnStatus.START_ERROR
