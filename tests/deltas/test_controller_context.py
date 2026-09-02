from __future__ import annotations

import pytest

from ki_dev.deltas import (
    BeadsDelta,
    ChangeMedium,
    CheckOutcome,
    CombinedDelta,
    ControllerContext,
    DeltaScope,
    GitDelta,
    RefBoundary,
    RoundStatus,
    VcsRef,
)


def _combined(scope: DeltaScope) -> CombinedDelta:
    git_ref = VcsRef(ChangeMedium.GIT, "a" * 40)
    bd_ref = VcsRef(ChangeMedium.BEADS, "dolt-1")
    git_boundary = RefBoundary(git_ref, git_ref)
    bd_boundary = RefBoundary(bd_ref, bd_ref)
    return CombinedDelta(
        scope=scope,
        git=GitDelta(boundary=git_boundary, files=(), patch=""),
        beads=BeadsDelta(boundary=bd_boundary, issues=(), summary=""),
    )


def test_round_status_reports_remaining():
    status = RoundStatus(current=2, limit=5)
    assert status.remaining == 3


@pytest.mark.parametrize(
    ("current", "limit"),
    [(0, 5), (3, 2)],
)
def test_round_status_rejects_invalid_counts(current: int, limit: int):
    with pytest.raises(ValueError, match="RoundStatus"):
        RoundStatus(current=current, limit=limit)


def test_check_outcome_requires_name():
    with pytest.raises(ValueError, match="name"):
        CheckOutcome(name="  ", passed=True)


def test_context_bundles_required_facts():
    ctx = ControllerContext(
        task="Implementiere X (ki-dev-ablauf-8dd.3)",
        step_delta=_combined(DeltaScope.STEP),
        round_status=RoundStatus(current=2, limit=5),
        open_objection="Test fuer Y fehlt.",
        checks=(CheckOutcome("pytest", passed=False, detail="1 fail"),),
        run_delta=_combined(DeltaScope.RUN),
    )
    assert ctx.step_delta.scope is DeltaScope.STEP
    assert ctx.run_delta.scope is DeltaScope.RUN
    assert ctx.open_objection == "Test fuer Y fehlt."
    assert ctx.checks[0].passed is False


def test_context_defaults_are_minimal():
    ctx = ControllerContext(
        task="Nur der Auftrag",
        step_delta=_combined(DeltaScope.STEP),
        round_status=RoundStatus(current=1, limit=1),
    )
    assert ctx.open_objection is None
    assert ctx.checks == ()
    assert ctx.run_delta is None


def test_context_rejects_empty_task():
    with pytest.raises(ValueError, match="task"):
        ControllerContext(
            task="   ",
            step_delta=_combined(DeltaScope.STEP),
            round_status=RoundStatus(current=1, limit=1),
        )


def test_context_enforces_delta_scopes():
    with pytest.raises(ValueError, match="step_delta"):
        ControllerContext(
            task="Auftrag",
            step_delta=_combined(DeltaScope.RUN),
            round_status=RoundStatus(current=1, limit=1),
        )
    with pytest.raises(ValueError, match="run_delta"):
        ControllerContext(
            task="Auftrag",
            step_delta=_combined(DeltaScope.STEP),
            round_status=RoundStatus(current=1, limit=1),
            run_delta=_combined(DeltaScope.STEP),
        )
