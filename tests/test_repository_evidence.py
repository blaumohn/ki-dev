from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ki_dev.loop import LoopTask
from ki_dev.repository_evidence import RepositoryEvidenceCollector


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def test_prepare_rejects_preexisting_foreign_changes(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@example.invalid")
    (repo / "tracked.txt").write_text("base\n")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "base")
    foreign = repo / "foreign.txt"
    foreign.write_text("must survive\n")
    task = LoopTask("run-1", "task", (), repo, "write")

    with pytest.raises(RuntimeError, match="fremde Aenderungen"):
        RepositoryEvidenceCollector().prepare(task, 1)

    assert foreign.read_text() == "must survive\n"
