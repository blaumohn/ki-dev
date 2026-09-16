from __future__ import annotations

from pathlib import Path

import pytest
from plumbum import CommandNotFound, local

from ki_dev.deltas import (
    ChangeMedium,
    DeltaScope,
    StepDeltaAssessment,
    WorkerSignal,
    assess_step_delta,
    build_run_delta,
    build_step_delta,
    capture_media_refs,
    checkpoint_step_result,
)

from .conftest import run_bd


def _bd_available() -> bool:
    try:
        local["bd"]
    except CommandNotFound:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _bd_available(), reason="bd lokal nicht installiert"
)

_MSG = "Schritt (ki-dev-ablauf-8dd.3)"


def _edit_git(repo: Path, name: str) -> None:
    (repo / name).write_text("print(1)\n", encoding="utf-8")


def test_capture_media_refs_covers_both(work_repo: Path):
    refs = capture_media_refs(work_repo)
    assert refs.git.medium is ChangeMedium.GIT
    assert refs.beads.medium is ChangeMedium.BEADS


def test_effective_step_reports_change(work_repo: Path):
    base = capture_media_refs(work_repo)
    _edit_git(work_repo, "feature.py")
    run_bd(work_repo, "q", "Aufgabe aus Schritt 1")
    result = checkpoint_step_result(work_repo, message=_MSG)

    step = build_step_delta(work_repo, base, result)
    assert step.scope is DeltaScope.STEP
    assert not step.is_empty
    assert [f.path for f in step.git.files] == ["feature.py"]
    assert len(step.beads.issues) == 1
    assert assess_step_delta(step) is StepDeltaAssessment.EFFECTIVE


def test_rounds_split_step_and_run_delta(work_repo: Path):
    run_base = capture_media_refs(work_repo)

    _edit_git(work_repo, "a.py")
    run_bd(work_repo, "q", "Aufgabe A")
    result_1 = checkpoint_step_result(work_repo, message=_MSG)
    step_1 = build_step_delta(work_repo, run_base, result_1)

    _edit_git(work_repo, "b.py")
    run_bd(work_repo, "q", "Aufgabe B")
    result_2 = checkpoint_step_result(work_repo, message=_MSG)
    step_2 = build_step_delta(work_repo, result_1, result_2)
    run_total = build_run_delta(work_repo, run_base, result_2)

    assert [f.path for f in step_1.git.files] == ["a.py"]
    assert [f.path for f in step_2.git.files] == ["b.py"]
    assert run_total.scope is DeltaScope.RUN
    assert sorted(f.path for f in run_total.git.files) == [
        "a.py",
        "b.py",
    ]
    assert len(run_total.beads.issues) == 2


def test_empty_step_is_not_success(work_repo: Path):
    base = capture_media_refs(work_repo)
    result = checkpoint_step_result(work_repo, message=_MSG)
    step = build_step_delta(work_repo, base, result)

    assert step.is_empty
    assert result.git == base.git
    assert (
        assess_step_delta(step) is StepDeltaAssessment.EMPTY_UNEXPLAINED
    )
    assert (
        assess_step_delta(step, WorkerSignal.NEEDS_DECISION)
        is StepDeltaAssessment.EMPTY_WITH_SIGNAL
    )
    assert (
        assess_step_delta(step, WorkerSignal.ESCALATE)
        is StepDeltaAssessment.EMPTY_WITH_SIGNAL
    )


def test_assess_step_delta_rejects_run_scope(work_repo: Path):
    base = capture_media_refs(work_repo)
    result = checkpoint_step_result(work_repo, message=_MSG)
    run_total = build_run_delta(work_repo, base, result)
    with pytest.raises(ValueError, match="STEP-Delta"):
        assess_step_delta(run_total)


def test_checkpoint_result_rejects_empty_msg(work_repo: Path):
    with pytest.raises(ValueError, match="Nachricht"):
        checkpoint_step_result(work_repo, message="")
