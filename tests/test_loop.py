from __future__ import annotations

import json
from pathlib import Path

import pytest

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
from ki_dev.loop import (
    BuildReport,
    LoopProtocolError,
    LoopTask,
    ReviewAction,
    parse_review_decision,
    run_review_round,
)


class FakeBuilder:
    def __init__(self) -> None:
        self.requests = []

    def build(self, request):
        self.requests.append(request)
        return BuildReport("Implementiert; pytest erfolgreich")


class FakeReviewer:
    def __init__(self, action: ReviewAction) -> None:
        self.action = action
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
def test_fake_build_review_cycle_reaches_typed_decision(action):
    builder = FakeBuilder()
    reviewer = FakeReviewer(action)
    task = LoopTask(
        "run-1", "Auftrag", ("bd:jbr.1",), Path("/work"), "write"
    )
    result = run_review_round(
        task=task,
        round_id=1,
        build_mode=builder,
        reviewer=reviewer,
        context_after_build=_context,
    )
    assert result.action is action
    assert builder.requests[0].task is task
    assert "result = 1" in reviewer.requests[0].evidence.text


@pytest.mark.parametrize(
    "payload",
    [
        "PASS",
        '{"run_id":"other","round_id":1,"action":"PASS","detail":""}',
        '{"run_id":"run-1","round_id":2,"action":"PASS","detail":""}',
        '{"run_id":"run-1","round_id":true,"action":"PASS","detail":""}',
        '{"run_id":"run-1","round_id":1,"action":"MAYBE","detail":""}',
        '{"run_id":"run-1","round_id":1,"action":"PASS"}',
    ],
)
def test_invalid_or_foreign_review_decisions_are_rejected(payload):
    with pytest.raises(LoopProtocolError):
        parse_review_decision(payload, run_id="run-1", round_id=1)


def test_context_binding_is_checked_after_build():
    wrong = _context()
    wrong = ControllerContext(
        "Fremder Auftrag", wrong.step_delta, wrong.round_status
    )
    task = LoopTask("run-1", "Auftrag", (), Path("/work"), "write")
    with pytest.raises(LoopProtocolError, match="fremdem Auftrag"):
        run_review_round(
            task=task,
            round_id=1,
            build_mode=FakeBuilder(),
            reviewer=FakeReviewer(ReviewAction.PASS),
            context_after_build=lambda: wrong,
        )


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
        }
    )
    assert (
        parse_review_decision(
            payload, run_id="run-1", round_id=1
        ).action
        is action
    )
