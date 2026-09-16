from __future__ import annotations

from pathlib import Path

import pytest

from ki_dev.executors import (
    CodexCliAdapter,
    Effort,
    TurnRequest,
    TurnResult,
    TurnStatus,
)

from .conftest import FakeRunner


def _request(**over: object) -> TurnRequest:
    base = {
        "session_id": "01J-codex-session",
        "message": "naechster schritt",
        "model": "gpt-5-codex",
        "effort": Effort.MEDIUM,
        "workdir": Path("/work"),
    }
    base.update(over)
    return TurnRequest(**base)  # type: ignore[arg-type]


def test_argv_uses_exec_resume():
    runner = FakeRunner()
    CodexCliAdapter(runner=runner).send_turn(_request())
    assert runner.argv[0] == "codex"
    assert runner.argv[1:3] == ("exec", "resume")
    assert "01J-codex-session" in runner.argv
    assert runner.argv[-1] == "-"


def test_session_and_model_translated():
    runner = FakeRunner()
    CodexCliAdapter(runner=runner).send_turn(_request())
    assert runner.value_after("resume") == "01J-codex-session"
    assert runner.value_after("--model") == "gpt-5-codex"


@pytest.mark.parametrize(
    ("effort", "expected"),
    [
        (Effort.LOW, "model_reasoning_effort=low"),
        (Effort.MEDIUM, "model_reasoning_effort=medium"),
        (Effort.HIGH, "model_reasoning_effort=high"),
    ],
)
def test_effort_maps_to_config_key(effort, expected):
    runner = FakeRunner()
    CodexCliAdapter(runner=runner).send_turn(_request(effort=effort))
    assert runner.value_after("-c") == expected


def test_message_goes_to_stdin():
    runner = FakeRunner()
    CodexCliAdapter(runner=runner).send_turn(_request())
    assert runner.stdin == "naechster schritt"
    assert "naechster schritt" not in runner.argv


def test_nonzero_exit_passed_through():
    failed = TurnResult(
        status=TurnStatus.NONZERO_EXIT,
        exit_code=7,
        stdout="",
        stderr="boom",
        argv=(),
        duration_s=0.5,
        error="CLI endete mit Exitstatus 7",
    )
    runner = FakeRunner(failed)
    result = CodexCliAdapter(runner=runner).send_turn(_request())
    assert result.status is TurnStatus.NONZERO_EXIT
    assert result.exit_code == 7
