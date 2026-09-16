from __future__ import annotations

from pathlib import Path

import pytest

from ki_dev.executors import (
    ClaudeCliAdapter,
    CodexCliAdapter,
    Effort,
    Executor,
    TurnRequest,
    TurnResult,
    TurnStatus,
)


def test_adapters_satisfy_contract():
    for adapter in (ClaudeCliAdapter(), CodexCliAdapter()):
        assert isinstance(adapter, Executor)
        assert hasattr(adapter, "send_turn")
        assert isinstance(adapter.name, str)


def test_result_ok_only_for_ok_status():
    ok = TurnResult(TurnStatus.OK, 0, "", "", (), 0.0)
    fail = TurnResult(TurnStatus.NONZERO_EXIT, 1, "", "", (), 0.0)
    assert ok.ok is True
    assert fail.ok is False


@pytest.mark.parametrize(
    ("kwargs", "exc"),
    [
        ({"session_id": ""}, ValueError),
        ({"message": ""}, ValueError),
        ({"model": ""}, ValueError),
        ({"effort": "high"}, TypeError),
    ],
)
def test_request_rejects_bad_fields(kwargs, exc):
    base = {
        "session_id": "s",
        "message": "m",
        "model": "mod",
        "effort": Effort.LOW,
        "workdir": Path("/work"),
    }
    base.update(kwargs)
    with pytest.raises(exc):
        TurnRequest(**base)


@pytest.mark.parametrize(
    ("kwargs", "exc"),
    [
        ({"workdir": Path("relative")}, ValueError),
        ({"env": {"": "x"}}, TypeError),
        ({"env": {"K": 1}}, TypeError),
    ],
)
def test_request_rejects_bad_workdir_and_env(kwargs, exc):
    base = {
        "session_id": "s",
        "message": "m",
        "model": "mod",
        "effort": Effort.LOW,
        "workdir": Path("/work"),
    }
    base.update(kwargs)
    with pytest.raises(exc):
        TurnRequest(**base)


def test_status_values_are_disjoint():
    assert len({s.value for s in TurnStatus}) == 4
