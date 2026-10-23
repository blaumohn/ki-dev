"""Sitzung je Rolle: beim ersten Aufruf angelegt, im Lauf abgelegt.

Ohne ``session_id`` im Profil sendet die Rolle ihren ersten Aufruf ohne
Sitzung; nach dessen Erfolg gilt die genannte ID für alle weiteren
Aufrufe, auch nach ``resume`` (``sessions/<rolle>.json`` im Lauf).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from ki_dev.adapter.agent import AgentReviewer, AgentWorker
from ki_dev.adapter.contract import (
    AgentTurnError,
    ReviewRequest,
    ReviewVocabulary,
    RunTask,
    WorkRequest,
)
from ki_dev.adapter.executors import (
    Access,
    Effort,
    TurnResult,
    TurnStatus,
)
from ki_dev.flow_ops.implement import cli as runner_cli
from ki_dev.run_store import RunStore, RunStoreError
from tests.executor_specs import BOOKED

OK = TurnResult(TurnStatus.OK, 0, "fertig", "", (), 1.0)


class Executor:
    """Antwortet mit festen Ergebnissen und merkt sich die Anfragen."""

    name = "fake"

    def __init__(self, *results: TurnResult) -> None:
        self.results = list(results)
        self.requests = []

    def send_turn(self, request):
        self.requests.append(request)
        return self.results.pop(0)


def _task(access_profile: str = "write") -> RunTask:
    return RunTask(
        "r-1",
        "Auftrag",
        (),
        Path("/work"),
        access_profile,
        acceptance_criteria=("Kriterium 1",),
    )


def _work(worker: AgentWorker, access_profile: str = "write") -> None:
    worker.work(WorkRequest(_task(access_profile), 1, "bauen", "a-1"))


def _worker(executor: Executor, **kwargs) -> AgentWorker:
    return AgentWorker(
        executor, None, "m", Effort.LOW, spec=BOOKED, **kwargs
    )


def test_first_successful_call_adopts_and_reports_the_session():
    executor = Executor(
        replace(OK, session_id="t-1"), replace(OK, session_id="t-1")
    )
    reported = []
    worker = _worker(executor, on_session=reported.append)
    _work(worker)
    _work(worker)
    assert [r.session_id for r in executor.requests] == [None, "t-1"]
    assert reported == ["t-1"]


def test_failed_first_call_keeps_the_role_without_session():
    failed = TurnResult(
        TurnStatus.NONZERO_EXIT, 1, "", "", (), 1.0, error="kaputt",
        session_id="t-1",
    )
    reported = []
    worker = _worker(Executor(failed), on_session=reported.append)
    with pytest.raises(AgentTurnError):
        _work(worker)
    assert worker.session_id is None
    assert reported == []


def test_new_session_without_reported_id_is_an_agent_error():
    worker = _worker(Executor(OK))
    with pytest.raises(AgentTurnError, match="ohne Sitzungs-ID"):
        _work(worker)


@pytest.mark.parametrize("access", list(Access))
def test_worker_access_follows_the_access_profile(access):
    executor = Executor(replace(OK, session_id="t-1"))
    _work(_worker(executor), access.value)
    assert executor.requests[0].access is access


def test_review_only_reads():
    executor = Executor(replace(OK, session_id="t-1"))
    reviewer = AgentReviewer(
        executor, None, "m", Effort.LOW, spec=BOOKED
    )
    vocabulary = ReviewVocabulary(("PASS",), "fix", "decision", {})
    reviewer.review(
        ReviewRequest(_task(), 1, "pruefen", vocabulary, "a-1")
    )
    assert executor.requests[0].access is Access.READ


def test_store_keeps_one_session_per_role(tmp_path):
    store = RunStore(tmp_path, "r-1")
    assert store.load_session("worker", "codex") is None
    store.save_session("worker", "codex", "t-1")
    store.save_session("worker", "codex", "t-1")
    assert store.load_session("worker", "codex") == "t-1"
    with pytest.raises(RunStoreError, match="widerspricht"):
        store.save_session("worker", "codex", "t-2")
    with pytest.raises(RunStoreError, match="passt nicht"):
        store.load_session("worker", "claude")
    with pytest.raises(RunStoreError, match="Rollenname"):
        store.load_session("../worker", "codex")


def test_role_without_profile_session_continues_stored_one(tmp_path):
    """``resume`` baut die Rollen neu: die beim ersten Aufruf angelegte
    Sitzung kommt aus dem Lauf, nicht aus dem Profil."""
    store = RunStore(tmp_path, "r-1")
    value = {"executor": "codex", "model": "m", "effort": "low"}

    def unwrapped(executor, role):
        del role
        return executor

    first = runner_cli._adapter(value, "worker", store, unwrapped)
    assert first.session_id is None
    first.on_session("t-1")
    again = runner_cli._adapter(value, "worker", store, unwrapped)
    assert again.session_id == "t-1"


def test_profile_session_is_used_without_storing(tmp_path):
    store = RunStore(tmp_path, "r-1")
    value = {
        "executor": "codex",
        "session_id": "019a-eigen",
        "model": "m",
        "effort": "low",
    }
    agent = runner_cli._adapter(value, "worker", store, lambda e, _: e)
    assert agent.session_id == "019a-eigen"
    assert agent.on_session is None
    assert not (store.run_dir / "sessions").exists()
