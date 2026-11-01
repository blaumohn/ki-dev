from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from ki_dev import repository_evidence
from ki_dev.adapter.contract import (
    BeadsChange,
    RunTask,
)
from ki_dev.deltas import ChangeMedium, MediaRefs, VcsRef
from ki_dev.repository_evidence import (
    CheckCommand,
    RepositoryEvidenceCollector,
    _checkpoint_message,
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
    task = RunTask(
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
    task = RunTask(
        "run-1", "task", (), repo, "write",
        acceptance_criteria=("Kriterium 1",),
    )

    with pytest.raises(RuntimeError, match="fremde Aenderungen"):
        RepositoryEvidenceCollector().prepare(task, 1)

    assert foreign.read_text() == "must survive\n"


def test_beads_change_compares_today_with_boundary(
    tmp_path: Path, monkeypatch
):
    """Gleicher Stand: keine Änderung, kein ``bd diff``. Anderer Stand:
    Grenze, heutiger Stand und lesbares Diff."""
    refs = {
        "git": {"medium": "git", "value": "g"},
        "beads": {"medium": "beads", "value": "b1"},
    }
    task = RunTask(
        run_id="r",
        task="t",
        sources=(),
        workdir=tmp_path,
        access_profile="write",
        acceptance_criteria=("AC",),
    )
    collector = RepositoryEvidenceCollector(checks=())
    today = VcsRef(ChangeMedium.BEADS, "b1")
    monkeypatch.setattr(
        repository_evidence, "capture_beads_ref", lambda _repo: today
    )
    assert collector.beads_change(task, refs) is None

    today = VcsRef(ChangeMedium.BEADS, "b2")
    monkeypatch.setattr(
        repository_evidence,
        "build_beads_delta",
        lambda _repo, _boundary: SimpleNamespace(summary="+ Added: x"),
    )
    assert collector.beads_change(task, refs) == BeadsChange(
        "b1", "b2", "+ Added: x"
    )


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


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        (
            ("bd:p-1.2", "docs/a.md"),
            "ki-dev run-1 Runde 3 (p-1.2)",
        ),
        (
            ("bd:p-1", "bd:p-2"),
            "ki-dev run-1 Runde 3 (p-1) (p-2)",
        ),
        (("docs/a.md",), "ki-dev run-1 Runde 3"),
    ],
)
def test_checkpoint_message_names_each_bead(sources, expected):
    """Der commit-msg-Hook der Beads-Integration verlangt am Zeilenende
    je Beads-ID eine eigene Klammer; ein Lauf ohne Bead hat keine."""
    task = RunTask(
        "run-1", "task", sources, Path("/repo"), "write",
        acceptance_criteria=("Kriterium 1",),
    )

    assert _checkpoint_message(task, 3) == expected
