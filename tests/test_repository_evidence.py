from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ki_dev.deltas import ChangeMedium, MediaRefs, VcsRef
from ki_dev.loop import LoopTask
from ki_dev.repository_evidence import (
    RepositoryEvidenceCollector,
    _decode_refs,
    _encode_refs,
)


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
