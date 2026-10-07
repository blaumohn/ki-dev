"""Öffentliche PM-Sicht des Beads-Journals: audit und index (rb2)."""

from datetime import UTC, datetime

import pytest

from ki_dev.beads_journal import cli, journal
from ki_dev.beads_journal.journal import JournalError
from ki_dev.beads_journal.publish import (
    Finding,
    audit_changes,
    orphans,
    render_index,
    scan_text,
)
from ki_dev.beads_journal.publish_cli import run_index
from tests.test_beads_journal import IDENTITY, git, issue, subjects

SECRET = "GEHEIM-7f3a"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "text, category",
    [
        ("siehe .local/notiz.md", "lokaler-verweis"),
        ("Pfad /home/agent/x", "absoluter-pfad"),
        ("Pfad /workspace/src", "absoluter-pfad"),
        ("an jemand@beispiel.de", "mailadresse"),
        ("token = abcdef123456", "zugangsdaten"),
        ("ghp_" + "a" * 30, "zugangsdaten"),
    ],
)
def test_scan_names_the_category(text, category):
    assert scan_text(text) == (category,)


@pytest.mark.parametrize(
    "text",
    [
        "x@users.noreply.github.com",
        "Co-Authored-By: Claude <noreply@anthropic.com>",
        "journal@test.invalid",
        "a@example.com",
        "docs/handoff.de.md und src/ki_dev/cli.py",
        "Bereich ~/.claude/projects",
        "bd-local/x und ../mdman",
    ],
)
def test_public_or_relative_text_is_no_finding(text):
    assert scan_text(text) == ()


def test_audit_findings_are_deduplicated_and_sorted():
    changes = [
        ("b2", "issues/x.json", "/home/a /home/b"),
        ("a1", "issues/y.json", ".local/x"),
        ("a1", "issues/y.json", ".local/y"),
    ]
    assert audit_changes(changes) == [
        Finding("a1", "issues/y.json", "lokaler-verweis"),
        Finding("b2", "issues/x.json", "absoluter-pfad"),
    ]


def test_orphans_are_journal_ids_missing_in_the_db():
    assert orphans(["c", "a", "b"], ["b"]) == ["a", "c"]


def test_index_is_sorted_marks_orphans_and_escapes_cells():
    issues = [
        {"id": "t-2", "title": "B | C", "status": "open"},
        {
            "id": "t-1",
            "title": "A\nzwei",
            "status": "closed",
            "issue_type": "task",
        },
    ]
    text = render_index(issues, ["t-2"], "2026-10-07T12:00:00Z", "abc")
    lines = text.splitlines()
    assert lines[0] == "# Beads-Journal – Vorgänge"
    assert "2026-10-07T12:00:00Z" in lines[2] and "`abc`" in lines[2]
    rows = [line for line in lines if line.startswith("| [")]
    assert rows == [
        "| [t-1](issues/t-1.json) | A zwei | closed | task |",
        "| [t-2](issues/t-2.json) | B \\| C | open · nicht in DB |  |",
    ]
    assert text == render_index(
        list(reversed(issues)), ["t-2"], "2026-10-07T12:00:00Z", "abc"
    )


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    for key, value in IDENTITY.items():
        git(path, "config", key, value)
    git(path, "commit", "-q", "--allow-empty", "-m", "start")
    return path


@pytest.fixture
def journal_dir(repo):
    path = repo / ".local" / "beads-journal"
    issues = [
        issue("t-1", description=f"siehe /home/agent/{SECRET}"),
        issue("t-2", issue_type="task"),
    ]
    journal.initialize(path, issues, IDENTITY)
    return path


def test_audit_reports_old_revisions_without_values(
    repo, journal_dir, capsys
):
    journal.commit_event(
        journal_dir,
        "update",
        issue("t-1", updated_at="2026-10-03T10:00:00Z"),
        1,
    )
    assert cli.main(["--repo", str(repo), "audit"]) == 1
    out = capsys.readouterr().out
    first = git(journal_dir, "rev-list", "--max-parents=0", "HEAD")
    assert f"{first[:10]} issues/t-1.json absoluter-pfad" in out
    assert "1 Befunde in 1 Revisionen" in out
    assert SECRET not in out and "/home" not in out


def test_audit_without_findings_exits_0(repo, capsys):
    path = repo / ".local" / "beads-journal"
    journal.initialize(path, [issue("t-1")], IDENTITY)
    assert cli.main(["--repo", str(repo), "audit"]) == 0
    assert "keine Privatbefunde" in capsys.readouterr().out


def test_index_marks_deleted_issues_and_commits_once(
    repo, journal_dir, monkeypatch, capsys
):
    monkeypatch.setattr(
        cli, "export_issues", lambda _root: [issue("t-1")]
    )
    before = git(journal_dir, "rev-list", "--count", "HEAD")
    assert cli.main(["--repo", str(repo), "index"]) == 0
    text = (journal_dir / "index.md").read_text()
    assert (
        "| [t-2](issues/t-2.json) | Titel t-2 | open · nicht in DB"
        in (text)
    )
    assert git(repo, "rev-parse", "--short=12", "HEAD").strip() in text
    assert subjects(journal_dir)[-1].startswith("index: Stand ")
    after = git(journal_dir, "rev-list", "--count", "HEAD")
    assert int(after) == int(before) + 1
    assert git(journal_dir, "status", "--porcelain") == ""
    assert "1 nicht in DB" in capsys.readouterr().out


def test_same_input_gives_the_same_index(repo, journal_dir):
    def export(_root):
        return [issue("t-1"), issue("t-2")]

    run_index(repo, journal_dir, export, now=lambda: NOW)
    first = (journal_dir / "index.md").read_bytes()
    (journal_dir / "index.md").write_text("veraendert")
    run_index(repo, journal_dir, export, now=lambda: NOW)
    assert (journal_dir / "index.md").read_bytes() == first


def test_export_failure_writes_no_index(repo, journal_dir, monkeypatch):
    def broken(_root):
        raise JournalError("bd export: Exit 3")

    monkeypatch.setattr(cli, "export_issues", broken)
    assert cli.main(["--repo", str(repo), "index"]) == 1
    assert not (journal_dir / "index.md").exists()


def test_inactive_journal_is_an_error(repo, capsys):
    assert cli.main(["--repo", str(repo), "audit"]) == 1
    assert "nicht eingerichtet" in capsys.readouterr().err
