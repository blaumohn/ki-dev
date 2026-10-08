from __future__ import annotations

import json
from pathlib import Path

import pytest

from ki_dev.adapter.agent import (
    AgentBuildMode,
)
from ki_dev.adapter.contract import (
    BuildReport,
    BuildRequest,
    ReviewRequest,
    RunTask,
)
from ki_dev.adapter.executors import Effort
from ki_dev.adapter.executors.contract import (
    ContextMeasurement,
    ContextStatus,
    TurnResult,
    TurnStatus,
)
from ki_dev.deltas import (
    BeadsDelta,
    ChangeMedium,
    CombinedDelta,
    ControllerContext,
    DeltaScope,
    GitDelta,
    GitFileChange,
    RefBoundary,
    RoundStatus,
    VcsRef,
)
from ki_dev.review_context import project_review_context
from ki_dev.review_decision import (
    ReviewAction,
)
from ki_dev.runner.review_output import (
    AgentProtocolError,
    bind_review_decision,
    parse_review_decision,
)


class FakeBuilder:
    def __init__(self) -> None:
        self.requests = []

    def build(self, request):
        self.requests.append(request)
        return BuildReport("Implementiert; pytest erfolgreich")


class FakeReviewer:
    def __init__(
        self, action: ReviewAction, requirement_ref="AC1"
    ) -> None:
        self.action = action
        self.requirement_ref = requirement_ref
        self.requests = []

    def review(self, request):
        self.requests.append(request)
        return json.dumps(
            {
                "run_id": request.task.run_id,
                "round_id": request.round_id,
                "action": self.action.value,
                "detail": "Test fehlt"
                if self.action is ReviewAction.CHANGES
                else "",
                "requirement_ref": self.requirement_ref
                if self.action is ReviewAction.CHANGES
                else None,
            }
        )


def _context() -> ControllerContext:
    git_a = VcsRef(ChangeMedium.GIT, "a")
    git_b = VcsRef(ChangeMedium.GIT, "b")
    bd = VcsRef(ChangeMedium.BEADS, "d")
    patch = (
        "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n"
        "@@ -0,0 +1 @@\n+result = 1\n"
    )
    delta = CombinedDelta(
        DeltaScope.STEP,
        GitDelta(
            RefBoundary(git_a, git_b),
            (GitFileChange("A", "app.py"),),
            patch,
        ),
        BeadsDelta(RefBoundary(bd, bd), (), ""),
    )
    return ControllerContext("Auftrag", delta, RoundStatus(1, 3))


@pytest.mark.parametrize(
    "action", [ReviewAction.CHANGES, ReviewAction.PASS]
)
def test_formal_review_output_becomes_typed_decision(action):
    """Ein Adapter liefert Rohtext; erst der Ausführer macht daraus ein
    geprüftes, an den Auftrag gebundenes Urteil."""
    reviewer = FakeReviewer(action)
    task = RunTask(
        "run-1",
        "Auftrag",
        ("bd:jbr.1",),
        Path("/work"),
        "write",
        acceptance_criteria=("Kriterium 1",),
    )
    request = ReviewRequest(
        task,
        1,
        BuildReport("Implementiert"),
        project_review_context(_context()),
    )
    raw = reviewer.review(request)
    decision = parse_review_decision(raw, run_id="run-1", round_id=1)
    assert bind_review_decision(decision, task).action is action
    assert "result = 1" in reviewer.requests[0].evidence.text


@pytest.mark.parametrize(
    "payload",
    [
        "PASS",
        '{"run_id":"other","round_id":1,"action":"PASS","detail":"",'
        '"requirement_ref":null}',
        '{"run_id":"run-1","round_id":2,"action":"PASS","detail":"",'
        '"requirement_ref":null}',
        '{"run_id":"run-1","round_id":true,"action":"PASS","detail":"",'
        '"requirement_ref":null}',
        '{"run_id":"run-1","round_id":1,"action":"MAYBE","detail":"",'
        '"requirement_ref":null}',
        '{"run_id":"run-1","round_id":1,"action":"PASS"}',
        '{"run_id":"run-1","round_id":1,"action":"PASS","detail":"",'
        '"requirement_ref":"AC1"}',
        '{"run_id":"run-1","round_id":1,"action":"CHANGES",'
        '"detail":"x","requirement_ref":""}',
        '{"run_id":"run-1","round_id":1,"action":"CHANGES",'
        '"detail":"x","requirement_ref":1}',
    ],
)
def test_invalid_or_foreign_review_decisions_are_rejected(payload):
    with pytest.raises(AgentProtocolError):
        parse_review_decision(payload, run_id="run-1", round_id=1)


@pytest.mark.parametrize(
    "action",
    [
        ReviewAction.CHANGES,
        ReviewAction.PASS,
        ReviewAction.NEEDS_DECISION,
        ReviewAction.ESCALATE,
    ],
)
def test_every_review_action_is_typed(action):
    detail = "" if action is ReviewAction.PASS else "Begruendung"
    payload = json.dumps(
        {
            "run_id": "run-1",
            "round_id": 1,
            "action": action.value,
            "detail": detail,
            "requirement_ref": "AC1"
            if action is ReviewAction.CHANGES
            else None,
        }
    )
    assert (
        parse_review_decision(
            payload, run_id="run-1", round_id=1
        ).action
        is action
    )


def _bound_task() -> RunTask:
    return RunTask(
        "run-1",
        "Auftrag",
        (),
        Path("/work"),
        "write",
        acceptance_criteria=(
            "Status meldet vorhandene Laeufe korrekt",
        ),
    )


def test_changes_with_known_reference_stays_changes():
    task = _bound_task()
    decision = parse_review_decision(
        json.dumps(
            {
                "run_id": "run-1",
                "round_id": 1,
                "action": "CHANGES",
                "detail": "Gueltiger Lauf wird faelschlich als "
                "fehlend gemeldet",
                "requirement_ref": "AC1",
            }
        ),
        run_id="run-1",
        round_id=1,
    )
    bound = bind_review_decision(decision, task)
    assert bound.action is ReviewAction.CHANGES
    assert bound.requirement_ref == "AC1"


@pytest.mark.parametrize("ref", [None, "AC9"])
def test_changes_without_bound_reference_becomes_needs_decision(ref):
    task = _bound_task()
    detail = "Neue checkpoints.sqlite-shm-Datei ist aufgetaucht"
    decision = parse_review_decision(
        json.dumps(
            {
                "run_id": "run-1",
                "round_id": 1,
                "action": "CHANGES",
                "detail": detail,
                "requirement_ref": ref,
            }
        ),
        run_id="run-1",
        round_id=1,
    )
    bound = bind_review_decision(decision, task)
    assert bound.action is ReviewAction.NEEDS_DECISION
    assert bound.requirement_ref is None
    assert detail in bound.detail


def test_non_changes_decisions_pass_through_binding_unchanged():
    task = _bound_task()
    decision = parse_review_decision(
        json.dumps(
            {
                "run_id": "run-1",
                "round_id": 1,
                "action": "PASS",
                "detail": "",
                "requirement_ref": None,
            }
        ),
        run_id="run-1",
        round_id=1,
    )
    assert bind_review_decision(decision, task) == decision


def test_acceptance_criteria_must_be_unique_and_nonempty():
    with pytest.raises(ValueError):
        RunTask(
            "run-1",
            "Auftrag",
            (),
            Path("/work"),
            "write",
            acceptance_criteria=(),
        )
    with pytest.raises(ValueError):
        RunTask(
            "run-1",
            "Auftrag",
            (),
            Path("/work"),
            "write",
            acceptance_criteria=("gleich", "gleich"),
        )


def test_build_prompt_includes_acceptance_criteria():
    """ygq: Abnahmekriterien muessen auch den Bauagenten erreichen,
    nicht nur den Reviewer -- sonst sind vermeidbare kostenpflichtige
    CHANGES-Runden fuer dort bereits bekannte Anforderungen moeglich."""

    class RecordingExecutor:
        name = "recording"

        def __init__(self) -> None:
            self.requests = []

        def send_turn(self, request):
            self.requests.append(request)
            return TurnResult(TurnStatus.OK, 0, "erledigt", "", (), 0.0)

        def measure_context(self, session_id):
            del session_id
            return ContextMeasurement(ContextStatus.UNSUPPORTED)

    executor = RecordingExecutor()
    build = AgentBuildMode(executor, "build-session", "m", Effort.LOW)
    task = RunTask(
        "run-1",
        "Auftrag",
        (),
        Path("/work"),
        "write",
        acceptance_criteria=(
            "Ausgabe ist deterministisch",
            "Kein Netzwerkzugriff",
        ),
    )
    build.build(BuildRequest(task, 1))
    message = executor.requests[0].message
    assert "AC1: Ausgabe ist deterministisch" in message
    assert "AC2: Kein Netzwerkzugriff" in message
