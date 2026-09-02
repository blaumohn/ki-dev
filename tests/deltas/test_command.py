from __future__ import annotations

import sys

import pytest

from ki_dev.deltas import DeltaCommandError, run_command


def _py(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_success_keeps_stdout_and_exit_zero():
    out = run_command(_py("print('fertig')"))
    assert out.exit_code == 0
    assert out.stdout.strip() == "fertig"
    assert out.require_success().strip() == "fertig"


def test_nonzero_exit_is_captured_not_raised():
    out = run_command(
        _py("import sys; sys.stderr.write('kaputt'); sys.exit(2)")
    )
    assert out.exit_code == 2
    assert "kaputt" in out.stderr


def test_require_success_raises_on_nonzero():
    out = run_command(_py("import sys; sys.exit(3)"))
    with pytest.raises(DeltaCommandError) as info:
        out.require_success()
    assert "Exitstatus 3" in str(info.value)


def test_missing_binary_raises_error():
    with pytest.raises(DeltaCommandError) as info:
        run_command(["ki-dev-fehlt-9f3c", "--version"])
    assert "nicht auffindbar" in str(info.value)


def test_argv_is_recorded_on_output():
    argv = _py("pass")
    assert run_command(argv).argv == tuple(argv)
