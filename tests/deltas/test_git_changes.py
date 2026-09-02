from __future__ import annotations

import re
from pathlib import Path

import pytest

from ki_dev.deltas import (
    ChangeMedium,
    RefBoundary,
    VcsRef,
    build_git_delta,
    capture_git_ref,
    checkpoint_git_step,
    run_command,
)

_SHA = re.compile(r"[0-9a-f]{40}")


def _write(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text, encoding="utf-8")


def _delta(repo: Path, base: VcsRef, result: VcsRef):
    return build_git_delta(repo, RefBoundary(base, result))


def _parents(repo: Path, commit: str) -> str:
    argv = [
        "git",
        "-C",
        str(repo),
        "rev-list",
        "--parents",
        "-n",
        "1",
        commit,
    ]
    return run_command(argv).require_success()


def test_capture_git_ref_gives_full_sha(git_repo: Path):
    first = capture_git_ref(git_repo)
    assert first.medium is ChangeMedium.GIT
    assert _SHA.fullmatch(first.value)
    assert capture_git_ref(git_repo) == first


def test_checkpoint_appends_one_commit(git_repo: Path):
    base = capture_git_ref(git_repo)
    _write(git_repo, "feature.py", "print(1)\n")
    result = checkpoint_git_step(git_repo, message="Schritt (x-1)")
    assert result != base
    assert base.value in _parents(git_repo, result.value)


def test_checkpoint_without_change_keeps_head(git_repo: Path):
    base = capture_git_ref(git_repo)
    result = checkpoint_git_step(git_repo, message="Leer (x-1)")
    assert result == base


def test_checkpoint_rejects_empty_message(git_repo: Path):
    with pytest.raises(ValueError, match="Nachricht"):
        checkpoint_git_step(git_repo, message="   ")


def test_git_delta_lists_files_and_patch(git_repo: Path):
    base = capture_git_ref(git_repo)
    _write(git_repo, "feature.py", "print(1)\n")
    result = checkpoint_git_step(git_repo, message="Schritt (x-1)")
    delta = _delta(git_repo, base, result)
    assert not delta.is_empty
    assert [f.path for f in delta.files] == ["feature.py"]
    assert delta.files[0].status == "A"
    assert "print(1)" in delta.patch


def test_git_delta_empty_for_same_ref(git_repo: Path):
    base = capture_git_ref(git_repo)
    delta = _delta(git_repo, base, base)
    assert delta.is_empty
    assert delta.files == ()
    assert delta.patch == ""


def test_rounds_keep_step_and_run_apart(git_repo: Path):
    ref_a = capture_git_ref(git_repo)
    _write(git_repo, "a.py", "a\n")
    ref_b = checkpoint_git_step(git_repo, message="Runde 1 (x-1)")
    _write(git_repo, "b.py", "b\n")
    ref_c = checkpoint_git_step(git_repo, message="Runde 2 (x-1)")

    step_two = _delta(git_repo, ref_b, ref_c)
    run_total = _delta(git_repo, ref_a, ref_c)

    assert [f.path for f in step_two.files] == ["b.py"]
    assert sorted(f.path for f in run_total.files) == ["a.py", "b.py"]


def test_git_delta_rejects_non_git_boundary(git_repo: Path):
    beads = VcsRef(ChangeMedium.BEADS, "deadbeef")
    with pytest.raises(ValueError, match="nicht git"):
        build_git_delta(git_repo, RefBoundary(beads, beads))
