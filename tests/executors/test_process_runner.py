from __future__ import annotations

import sys

from ki_dev.executors import run_cli_turn
from ki_dev.executors.contract import TurnStatus


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_success_reports_ok_with_stdout():
    result = run_cli_turn(
        _py("import sys; sys.stdout.write('fertig')"),
        stdin="",
        timeout_s=10,
    )
    assert result.status is TurnStatus.OK
    assert result.ok is True
    assert result.exit_code == 0
    assert result.stdout == "fertig"
    assert result.error is None


def test_stdin_is_forwarded():
    result = run_cli_turn(
        _py("import sys; sys.stdout.write(sys.stdin.read())"),
        stdin="hallo-turn",
        timeout_s=10,
    )
    assert result.stdout == "hallo-turn"


def test_nonzero_exit_distinct_from_ok():
    result = run_cli_turn(
        _py("import sys; sys.stderr.write('nope'); sys.exit(3)"),
        stdin="",
        timeout_s=10,
    )
    assert result.status is TurnStatus.NONZERO_EXIT
    assert result.exit_code == 3
    assert result.stderr == "nope"
    assert result.error is not None


def test_timeout_has_no_exit_code():
    result = run_cli_turn(
        _py("import time; time.sleep(5)"),
        stdin="",
        timeout_s=0.2,
    )
    assert result.status is TurnStatus.TIMEOUT
    assert result.exit_code is None
    assert "Zeitueberschreitung" in result.error


def test_start_failure_is_its_own_status():
    result = run_cli_turn(
        ["ki-dev-nonexistent-binary-9f3c"],
        stdin="",
        timeout_s=10,
    )
    assert result.status is TurnStatus.START_ERROR
    assert result.exit_code is None
    assert "Prozessstart fehlgeschlagen" in result.error


def test_argv_is_recorded():
    argv = _py("pass")
    result = run_cli_turn(argv, stdin="", timeout_s=10)
    assert result.argv == tuple(argv)


def test_cwd_binds_child_process_to_given_worktree(tmp_path):
    result = run_cli_turn(
        _py("import os, sys; sys.stdout.write(os.getcwd())"),
        stdin="",
        timeout_s=10,
        cwd=tmp_path,
    )
    assert result.stdout == str(tmp_path)


def test_env_overrides_ambient_variable_for_child_process(monkeypatch):
    monkeypatch.setenv("KI_DEV_TEST_MARKER", "ambient")
    result = run_cli_turn(
        _py(
            "import os, sys; "
            "sys.stdout.write(os.environ.get('KI_DEV_TEST_MARKER', ''))"
        ),
        stdin="",
        timeout_s=10,
        env={"KI_DEV_TEST_MARKER": "bound"},
    )
    assert result.stdout == "bound"
