from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ki_dev.deltas import ChangeMedium, MediaRefs, VcsRef
from ki_dev.loop import LoopTask
from ki_dev.repository_evidence import (
    CheckCommand,
    RepositoryEvidenceCollector,
    _decode_refs,
    _encode_refs,
    _run_check,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def test_check_tests_bound_worktree_not_leaked_pythonpath(
    tmp_path: Path, monkeypatch
):
    """Ohne technische Bindung wuerde eine geerbte PYTHONPATH aus der
    Orchestrierung (hier auf einen fremden Quellstand zeigend) den
    Pruefauftrag denselben Namen aus dem falschen Verzeichnis
    importieren lassen, obwohl ``cwd`` bereits korrekt auf den
    konfigurierten Worktree zeigt (p0h.3)."""
    poisoned_src = tmp_path / "poisoned" / "src"
    (poisoned_src / "pkgname").mkdir(parents=True)
    (poisoned_src / "pkgname" / "__init__.py").write_text(
        "MARKER = 'poisoned'\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(poisoned_src))

    worktree = tmp_path / "worktree"
    worktree_src = worktree / "src"
    (worktree_src / "pkgname").mkdir(parents=True)
    (worktree_src / "pkgname" / "__init__.py").write_text(
        "MARKER = 'worktree'\n"
    )
    task = LoopTask(
        "run-1",
        "task",
        (),
        worktree,
        "write",
        acceptance_criteria=("Kriterium 1",),
        env={"PYTHONPATH": str(worktree_src)},
    )
    check = CheckCommand(
        "marker",
        (
            sys.executable,
            "-c",
            "import pkgname, sys; sys.stdout.write(pkgname.MARKER)",
        ),
    )

    outcome = _run_check(task, check)

    assert outcome.passed is True
    assert outcome.detail == "worktree"


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
    task = LoopTask(
        "run-1", "task", (), repo, "write",
        acceptance_criteria=("Kriterium 1",),
    )

    with pytest.raises(RuntimeError, match="fremde Aenderungen"):
        RepositoryEvidenceCollector().prepare(task, 1)

    assert foreign.read_text() == "must survive\n"


def test_encode_refs_uses_primitive_medium_values():
    refs = MediaRefs(
        VcsRef(ChangeMedium.GIT, "g1"), VcsRef(ChangeMedium.BEADS, "b1")
    )

    encoded = _encode_refs(refs)

    assert encoded == {
        "git": {"medium": "git", "value": "g1"},
        "beads": {"medium": "beads", "value": "b1"},
    }
    assert type(encoded["git"]["medium"]) is str
    assert type(encoded["beads"]["medium"]) is str
    # Checkpoint-faehig: keine Enum-Instanzen, nur JSON-Primitive.
    json.dumps(encoded)


def test_encode_decode_refs_roundtrip():
    refs = MediaRefs(
        VcsRef(ChangeMedium.GIT, "g1"), VcsRef(ChangeMedium.BEADS, "b1")
    )

    assert _decode_refs(_encode_refs(refs)) == refs
