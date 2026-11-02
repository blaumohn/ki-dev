"""``ki-dev -f implement history``: Verlauf eines Laufs für Menschen."""

from __future__ import annotations

from ki_dev.flow_ops.implement import cli as runner_cli
from ki_dev.flow_ops.implement.history import (
    WIDTH,
    _round_lines,
    run_history,
)
from ki_dev.flow_ops.implement.runtime import StaticEvidenceCollector
from ki_dev.repository_finalization import StaticFinalizer
from ki_dev.run_store import RunStore
from tests.test_runner_runtime import _context


def _without_findings(lines: list[str]) -> list[str]:
    """Der Verlauf ohne die Antworten auf die Prüffragen; die prüft
    ``tests/test_review_findings.py``."""
    return [line for line in lines if not line.startswith(" " * 6)]


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

    lines = _without_findings(run_history(RunStore(runs, "r-1")))

    assert lines[0] == "Lauf r-1: passed nach 2 Runden"
    assert lines[1].split() == ["Runde", "1", "Umsetzer", "geändert:",
                                "app.py"]
    assert lines[2].split()[:4] == ["Runde", "1", "Review", "fix"]
    assert lines[4].split()[:4] == ["Runde", "2", "Review", "PASS"]
    assert lines[-1].split()[0] == "Abschluss"
    assert all(len(line) <= WIDTH for line in lines)


def test_history_shows_halt_then_human_answer_before_next_review(
    monkeypatch, tmp_path
):
    """Ein Halt steht als eigene Zeile da; nach ``resume --answer``
    bleibt das erste Urteil sichtbar, die Antwort des Menschen steht
    vor dem Urteil, das sie erhalten hat."""
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
        "review": {"executor": "mock", "answers": ["decision"]},
        "tests": [],
    }
    runs = tmp_path / "runs"
    halted = runner_cli.start_run(config, run_id="r-1", runs_dir=runs)
    assert halted.status == "waiting_decision"
    lines = _without_findings(run_history(RunStore(runs, "r-1")))
    review = ["Runde", "1", "Review", "decision:"]
    assert lines[-2].split()[:4] == review
    assert lines[-1].split() == [
        "Halt", "wartet", "auf", "Entscheidung", "(Bead", "ändern,",
        "resume)",
    ]

    result = runner_cli.resume_run(
        "r-1",
        runs_dir=runs,
        answer="Test anpassen",
        overrides={
            "review": {"executor": "mock", "answers": ["fix", "PASS"]}
        },
    )
    assert result.status == "passed"

    lines = _without_findings(run_history(RunStore(runs, "r-1")))
    assert [line.split()[:4] for line in lines[1:5]] == [
        ["Runde", "1", "Umsetzer", "geändert:"],
        ["Runde", "1", "Review", "decision:"],
        ["Runde", "1", "Mensch", "Test"],
        ["Runde", "1", "Review", "fix"],
    ]
    assert lines[-1].split()[0] == "Abschluss"


def test_history_names_bead_change_read_by_resume(
    monkeypatch, tmp_path
):
    """``resume`` liest den Auftrag neu (``refresh``, sonst der Bead);
    ein geändertes Kriterium ist die Entscheidung des Menschen."""
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
        "review": {"executor": "mock", "answers": ["decision"]},
        "tests": [],
    }
    runs = tmp_path / "runs"
    runner_cli.start_run(config, run_id="r-1", runs_dir=runs)

    result = runner_cli.resume_run(
        "r-1",
        runs_dir=runs,
        answer=None,
        overrides={
            "review": {"executor": "mock", "answers": ["fix", "PASS"]}
        },
        refresh=lambda _: {"acceptance_criteria": ["Kriterium neu"]},
    )

    assert result.status == "passed"
    lines = _without_findings(run_history(RunStore(runs, "r-1")))
    assert [line.split()[:5] for line in lines[3:5]] == [
        ["Runde", "1", "Mensch", "AC1", "geändert"],
        ["Runde", "1", "Review", "fix", "(AC1):"],
    ]
    assert sum("Mensch" in line for line in lines) == 1


def test_history_wraps_review_reason_the_human_decides_on():
    """Bei ``decision`` braucht der Mensch die Begründung des Reviews:
    umbrochen statt nach einer Zeile gekürzt; ``fix`` bleibt eine
    Zeile."""
    reason = (
        "AC1 verlangt is_newer('1.10.0', '1.9.0') is True, die "
        "zweite Assertion in test_version.py das Gegenteil; AC2 "
        "verbietet, sie zu ändern."
    )

    def review(event):
        return {
            "decision": {
                "event": event,
                "detail": reason,
                "requirement_ref": None,
            },
            "decisions": [],
        }

    lines, _, _ = _round_lines(1, {"review": [review("decision")]}, 0)
    assert len(lines) > 1
    shown = " ".join(" ".join(lines).split()[3:])
    assert shown == f"decision: {reason}"
    assert all(len(line) <= WIDTH for line in lines)

    lines, _, _ = _round_lines(1, {"review": [review("fix")]}, 0)
    assert len(lines) == 1
    assert lines[0].endswith("…")
