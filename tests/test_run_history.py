"""``ki-dev -f implement history``: Verlauf eines Laufs für Menschen."""

from __future__ import annotations

from ki_dev.flow_ops.implement import cli as runner_cli
from ki_dev.flow_ops.implement.history import WIDTH, run_history
from ki_dev.flow_ops.implement.runtime import StaticEvidenceCollector
from ki_dev.repository_finalization import StaticFinalizer
from ki_dev.run_store import RunStore
from tests.test_runner_runtime import _context


def test_history_names_changes_review_answers_and_finalization(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        runner_cli,
        "RepositoryEvidenceCollector",
        lambda **_: StaticEvidenceCollector((_context(1), _context(2))),
    )
    monkeypatch.setattr(
        runner_cli, "_finalizer", lambda _: StaticFinalizer()
    )
    config = {
        "task": "Auftrag",
        "acceptance_criteria": ["Kriterium 1"],
        "sources": [],
        "workdir": str(tmp_path),
        "access_profile": "write",
        "finalization": {
            "target_workdir": str(tmp_path),
            "target_ref": "refs/heads/main",
            "commit_message": "Abschluss",
            "data_mode": "file_proposal",
        },
        "worker": {"executor": "mock"},
        "review": {"executor": "mock", "answers": ["fix", "PASS"]},
        "tests": [],
    }
    runs = tmp_path / "runs"
    result = runner_cli.start_run(config, run_id="r-1", runs_dir=runs)
    assert result.status == "passed"

    lines = run_history(RunStore(runs, "r-1"))

    assert lines[0] == "Lauf r-1: passed nach 2 Runden"
    assert lines[1].split() == ["Runde", "1", "Umsetzer", "geändert:",
                                "app.py"]
    assert lines[2].split()[:4] == ["Runde", "1", "Review", "fix"]
    assert lines[4].split()[:4] == ["Runde", "2", "Review", "PASS"]
    assert lines[-1].split()[0] == "Abschluss"
    assert all(len(line) <= WIDTH for line in lines)
