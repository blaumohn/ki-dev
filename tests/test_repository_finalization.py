from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import ki_dev.repository_finalization
from ki_dev.deltas import ChangeMedium, VcsRef
from ki_dev.repository_finalization import (
    FinalizationFailure,
    RepositoryFinalizer,
)


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return done.stdout.strip()


def _refs(git: str, beads: str = "dolt-base") -> dict[str, object]:
    return {
        "git": {"medium": "git", "value": git},
        "beads": {"medium": "beads", "value": beads},
    }


@pytest.fixture
def finalization_repo(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        ki_dev.repository_finalization,
        "capture_beads_ref",
        lambda _repo: VcsRef(ChangeMedium.BEADS, "dolt-base"),
    )
    target = tmp_path / "target"
    source = tmp_path / "source"
    target.mkdir()
    _git(target, "init", "-q", "-b", "main")
    _git(target, "config", "user.name", "test")
    _git(target, "config", "user.email", "test@example.invalid")
    (target / "result.txt").write_text("base\n", encoding="utf-8")
    _git(target, "add", "result.txt")
    _git(target, "commit", "-q", "-m", "base")
    base = _git(target, "rev-parse", "HEAD")
    _git(
        target,
        "worktree",
        "add",
        "-q",
        "-b",
        "review",
        str(source),
        base,
    )
    (source / "result.txt").write_text("reviewed\n", encoding="utf-8")
    _git(source, "add", "result.txt")
    _git(source, "commit", "-q", "-m", "reviewed")
    reviewed = _git(source, "rev-parse", "HEAD")
    finalizer = RepositoryFinalizer(
        target,
        "refs/heads/main",
        "Kontrollierter Abschluss (test-1)",
    )
    return target, source, base, reviewed, finalizer


def _freeze(
    source, base, reviewed, finalizer, *, reviewed_beads="dolt-base"
):
    return finalizer.freeze(
        source=source,
        run_id="run-1",
        base_refs=_refs(base),
        reviewed_refs=_refs(reviewed, reviewed_beads),
    )


def test_exact_reviewed_tree_is_fast_forwarded(finalization_repo):
    target, source, base, reviewed, finalizer = finalization_repo
    frozen = _freeze(source, base, reviewed, finalizer)
    final = finalizer.finalize_history(frozen)

    assert finalizer.verify(frozen, final)["ok"] is True
    assert finalizer.integrate(frozen, final)["ok"] is True
    assert _git(target, "rev-parse", "HEAD") == final["final_commit"]
    assert _git(target, "rev-parse", "HEAD^") == base
    assert (
        _git(target, "rev-parse", "HEAD^{tree}")
        == frozen["reviewed_tree"]
    )
    assert (target / "result.txt").read_text() == "reviewed\n"


def test_integration_is_idempotent_after_success(finalization_repo):
    target, source, base, reviewed, finalizer = finalization_repo
    frozen = _freeze(source, base, reviewed, finalizer)
    final = finalizer.finalize_history(frozen)

    assert finalizer.integrate(frozen, final)["ok"] is True
    first = _git(target, "rev-parse", "HEAD")
    assert finalizer.integrate(frozen, final)["ok"] is True
    assert _git(target, "rev-parse", "HEAD") == first


def test_target_drift_stops_before_integration(finalization_repo):
    target, source, base, reviewed, finalizer = finalization_repo
    frozen = _freeze(source, base, reviewed, finalizer)
    final = finalizer.finalize_history(frozen)
    (target / "foreign.txt").write_text("foreign\n")
    _git(target, "add", "foreign.txt")
    _git(target, "commit", "-q", "-m", "foreign")
    drift = _git(target, "rev-parse", "HEAD")

    result = finalizer.integrate(frozen, final)

    assert result["ok"] is False
    assert "gedriftet" in str(result["detail"])
    assert _git(target, "rev-parse", "HEAD") == drift


def test_foreign_uncommitted_changes_are_preserved(finalization_repo):
    target, source, base, reviewed, finalizer = finalization_repo
    frozen = _freeze(source, base, reviewed, finalizer)
    final = finalizer.finalize_history(frozen)
    foreign = target / "foreign.txt"
    foreign.write_text("do not touch\n")

    result = finalizer.integrate(frozen, final)

    assert result["ok"] is False
    assert "fremde Aenderungen" in str(result["detail"])
    assert foreign.read_text() == "do not touch\n"
    assert _git(target, "rev-parse", "HEAD") == base


def test_tree_deviation_is_rejected(finalization_repo):
    target, source, base, reviewed, finalizer = finalization_repo
    frozen = _freeze(source, base, reviewed, finalizer)
    final = {"final_commit": base}

    result = finalizer.verify(frozen, final)

    assert result["ok"] is False
    assert "Baum weicht" in str(result["detail"])


def test_git_integration_failure_does_not_report_success(
    finalization_repo, monkeypatch
):
    target, source, base, reviewed, finalizer = finalization_repo
    frozen = _freeze(source, base, reviewed, finalizer)
    final = finalizer.finalize_history(frozen)
    original = ki_dev.repository_finalization._git

    def fail_merge(repo, *args, env=None):
        if args[:2] == ("merge", "--ff-only"):
            raise FinalizationFailure("simulierter Integrationsfehler")
        return original(repo, *args, env=env)

    monkeypatch.setattr(
        ki_dev.repository_finalization, "_git", fail_merge
    )

    result = finalizer.integrate(frozen, final)

    assert result["ok"] is False
    assert "Integrationsfehler" in str(result["detail"])
    assert original(target, "rev-parse", "HEAD") == base


def test_direct_beads_writes_are_explicitly_rejected(finalization_repo):
    _, source, base, reviewed, finalizer = finalization_repo

    with pytest.raises(FinalizationFailure, match="dateibasierten"):
        _freeze(
            source,
            base,
            reviewed,
            finalizer,
            reviewed_beads="dolt-changed",
        )


def test_beads_drift_after_review_is_rejected(
    finalization_repo, monkeypatch
):
    _, source, base, reviewed, finalizer = finalization_repo
    monkeypatch.setattr(
        ki_dev.repository_finalization,
        "capture_beads_ref",
        lambda _repo: VcsRef(ChangeMedium.BEADS, "foreign-dolt"),
    )

    with pytest.raises(FinalizationFailure, match="gedriftet"):
        _freeze(source, base, reviewed, finalizer)


def test_unsupported_db_mode_is_rejected(tmp_path: Path):
    with pytest.raises(ValueError, match="isolierten"):
        RepositoryFinalizer(
            tmp_path,
            "refs/heads/main",
            "message",
            data_mode="beads_direct",
        )
