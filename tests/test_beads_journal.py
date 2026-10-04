"""Beads-Journal: Hook-Aufrufe gegen ein Journal in tmp_path."""

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from ki_dev.beads_journal import cli, journal
from ki_dev.beads_journal.git import GitError
from ki_dev.beads_journal.journal import ERRORS_LOG, MARKER

ROOT = Path(__file__).resolve().parents[1]
SECRET = "GEHEIM-7f3a"
IDENTITY = {
    "user.name": "Journal Test",
    "user.email": "journal@test.invalid",
}


def issue(
    issue_id="t-1",
    status="open",
    updated_at="2026-10-02T10:00:00Z",
    **extra,
):
    return {
        "id": issue_id,
        "title": f"Titel {issue_id}",
        "status": status,
        "updated_at": updated_at,
        **extra,
    }


def git(directory, *args):
    return subprocess.run(
        ["git", "-C", str(directory), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def subjects(directory):
    return git(directory, "log", "--format=%s").splitlines()[::-1]


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    for key, value in IDENTITY.items():
        git(path, "config", key, value)
    return path


@pytest.fixture
def journal_dir(repo):
    path = repo / ".local" / "beads-journal"
    journal.initialize(path, [], IDENTITY)
    return path


def call_hook(monkeypatch, repo, event, payload, hook_id=None):
    if hook_id is None:
        hook_id = payload["id"] if isinstance(payload, dict) else "t-1"
    data = (
        payload
        if isinstance(payload, bytes)
        else json.dumps(payload).encode()
    )
    monkeypatch.setattr(
        sys, "stdin", io.TextIOWrapper(io.BytesIO(data))
    )
    return cli.main(["--repo", str(repo), "hook", hook_id, event])


def hook_process(repo, event, payload):
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "ki_dev.beads_journal",
            "--repo",
            str(repo),
            "hook",
            payload["id"],
            event,
        ],
        stdin=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )


def normalized(payload):
    return (
        json.dumps(
            payload, sort_keys=True, indent=2, ensure_ascii=False
        )
        + "\n"
    )


def test_create_update_close_commit_each_event(
    monkeypatch, repo, journal_dir
):
    events = [
        ("create", issue()),
        (
            "update",
            issue(
                status="in_progress", updated_at="2026-10-02T11:00:00Z"
            ),
        ),
        (
            "close",
            issue(
                status="closed",
                updated_at="2026-10-02T12:00:00.123456789Z",
            ),
        ),
    ]
    for event, payload in events:
        assert call_hook(monkeypatch, repo, event, payload) == 0

    assert subjects(journal_dir)[1:] == [
        "create t-1: Titel t-1 [open]",
        "update t-1: Titel t-1 [in_progress]",
        "close t-1: Titel t-1 [closed]",
    ]
    stored = (journal_dir / "issues" / "t-1.json").read_text(
        encoding="utf-8"
    )
    assert stored == normalized(events[-1][1])
    assert git(journal_dir, "status", "--porcelain") == ""


def test_identical_payload_gives_two_commits(
    monkeypatch, repo, journal_dir
):
    for _ in range(2):
        assert call_hook(monkeypatch, repo, "update", issue()) == 0

    assert (
        subjects(journal_dir)[1:]
        == ["update t-1: Titel t-1 [open]"] * 2
    )


def test_late_payload_keeps_newer_file(monkeypatch, repo, journal_dir):
    newer = issue(
        status="closed", updated_at="2026-10-02T12:00:00+02:00"
    )
    older = issue(status="open", updated_at="2026-10-02T09:59:59Z")
    call_hook(monkeypatch, repo, "close", newer)

    assert call_hook(monkeypatch, repo, "update", older) == 0

    assert (
        subjects(journal_dir)[-1]
        == "update t-1: Titel t-1 [open] (verspätet)"
    )
    assert (
        git(journal_dir, "show", "--format=", "--name-only", "HEAD")
        == ""
    )
    stored = json.loads(
        (journal_dir / "issues" / "t-1.json").read_text()
    )
    assert stored["status"] == "closed"


@pytest.mark.parametrize(
    "same_second",
    ["2026-10-02T10:00:00Z", "2026-10-02T10:00:00.025555583Z"],
)
def test_same_second_without_fraction_is_not_late(
    monkeypatch, repo, journal_dir, same_second
):
    # create trägt Nanosekunden, bd liefert danach die DB-Sekunde.
    created = issue(updated_at="2026-10-02T10:00:00.025555584Z")
    updated = issue(status="in_progress", updated_at=same_second)
    call_hook(monkeypatch, repo, "create", created)

    assert call_hook(monkeypatch, repo, "update", updated) == 0

    assert (
        subjects(journal_dir)[-1]
        == "update t-1: Titel t-1 [in_progress]"
    )
    stored = json.loads(
        (journal_dir / "issues" / "t-1.json").read_text()
    )
    assert stored == updated


def test_earlier_second_is_late(monkeypatch, repo, journal_dir):
    created = issue(updated_at="2026-10-02T10:00:00.025555584Z")
    earlier = issue(
        status="in_progress", updated_at="2026-10-02T09:59:59.999Z"
    )
    call_hook(monkeypatch, repo, "create", created)

    assert call_hook(monkeypatch, repo, "update", earlier) == 0

    assert (
        subjects(journal_dir)[-1]
        == "update t-1: Titel t-1 [in_progress] (verspätet)"
    )
    stored = json.loads(
        (journal_dir / "issues" / "t-1.json").read_text()
    )
    assert stored == created


def test_parallel_hooks_each_commit(repo, journal_dir):
    payloads = [issue(f"t-{number}") for number in range(5)]
    processes = [
        hook_process(repo, "create", payload) for payload in payloads
    ]
    for process, payload in zip(processes, payloads, strict=True):
        process.stdin.write(json.dumps(payload).encode())
        process.stdin.close()
    for process in processes:
        process.wait(timeout=10)

    assert [process.returncode for process in processes] == [0] * 5
    assert sorted(subjects(journal_dir)[1:]) == sorted(
        f"create t-{number}: Titel t-{number} [open]"
        for number in range(5)
    )


def test_lock_timeout_logs_without_commit(
    monkeypatch, repo, journal_dir
):
    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import sys; from filelock import FileLock;"
            f"lock = FileLock({str(journal_dir / '.lock')!r});"
            "lock.acquire();"
            "print('gesperrt', flush=True); sys.stdin.read()",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "gesperrt"
        monkeypatch.setattr(journal, "LOCK_TIMEOUT", 0.2)

        assert call_hook(monkeypatch, repo, "update", issue()) == 1
    finally:
        holder.communicate("", timeout=10)

    assert subjects(journal_dir) == ["init: 0 Issues aus bd export"]
    log = (journal_dir / ERRORS_LOG).read_text()
    assert "update t-1: Sperre nicht binnen 0.2 s erhalten" in log


@pytest.mark.parametrize(
    ("payload", "hook_id", "reason"),
    [
        (
            {
                "id": "t-1",
                "status": "open",
                "updated_at": "2026-10-02T10:00:00Z",
            },
            "t-1",
            "issue.title: Pflichtfeld fehlt",
        ),
        (
            issue(updated_at=SECRET),
            "t-1",
            "issue.updated_at: ungültiges Format",
        ),
        (issue(title=[SECRET]), "t-1", "issue.title: falscher Typ"),
        (
            issue(updated_at="2026-02-30T10:00:00Z"),
            "t-1",
            "issue.updated_at: ungültiges Format",
        ),
        (
            issue(updated_at="2026-10-02T10:00:00+00:99"),
            "t-1",
            "issue.updated_at: ungültiges Format",
        ),
        (
            issue(issue_id=f"../{SECRET}"),
            f"../{SECRET}",
            "issue.id: ungültiges Format",
        ),
        (issue(), "t-2", "issue.id: passt nicht zur Hook-ID"),
        (f"{{{SECRET}".encode(), "t-1", "Nutzlast: kein JSON"),
    ],
)
def test_invalid_payload_logs_field_path_without_value(
    monkeypatch, repo, journal_dir, payload, hook_id, reason
):
    assert call_hook(monkeypatch, repo, "update", payload, hook_id) == 1

    assert subjects(journal_dir) == ["init: 0 Issues aus bd export"]
    log = (journal_dir / ERRORS_LOG).read_text()
    assert reason in log
    assert SECRET not in log
    assert list((journal_dir / "issues").iterdir()) == []


def test_unknown_event_is_logged(monkeypatch, repo, journal_dir):
    assert call_hook(monkeypatch, repo, "delete", issue()) == 1

    assert (
        "? t-1: event: unbekannter Wert"
        in (journal_dir / ERRORS_LOG).read_text()
    )


def test_without_marker_hook_ends_without_writing(monkeypatch, repo):
    before = sorted(repo.rglob("*"))

    assert call_hook(monkeypatch, repo, "update", b"kein json") == 0

    assert sorted(repo.rglob("*")) == before


def test_journal_folder_without_marker_stays_untouched(
    monkeypatch, repo, journal_dir
):
    (journal_dir / MARKER).unlink()

    assert call_hook(monkeypatch, repo, "update", issue()) == 0

    assert not (journal_dir / ERRORS_LOG).exists()
    assert len(subjects(journal_dir)) == 1


def test_hook_outside_git_repo_fails(monkeypatch, tmp_path):
    assert call_hook(monkeypatch, tmp_path, "update", issue()) == 1


def test_inherited_git_dir_does_not_redirect_commit(
    monkeypatch, repo, journal_dir
):
    monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(repo / ".git" / "index"))

    assert call_hook(monkeypatch, repo, "create", issue()) == 0

    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_INDEX_FILE")
    assert subjects(journal_dir)[-1] == "create t-1: Titel t-1 [open]"
    assert git(repo, "rev-list", "--all") == ""


def fake_bd(directory, monkeypatch, rows):
    script = directory / "bin" / "bd"
    script.parent.mkdir()
    lines = "".join(json.dumps(row) + "\n" for row in rows)
    script.write_text(f"#!/bin/sh\ncat <<'EOF'\n{lines}EOF\n")
    script.chmod(0o755)
    monkeypatch.setattr(cli, "BD_PROGRAM", str(script))


def test_init_fills_once_from_bd_export(
    monkeypatch, tmp_path, repo, capsys
):
    rows = [
        {"_type": "issue", **issue("t-1")},
        {"_type": "issue", **issue("t-2")},
    ]
    fake_bd(tmp_path, monkeypatch, rows)
    journal_dir = repo / ".local" / "beads-journal"

    assert cli.main(["--repo", str(repo), "init"]) == 0
    assert cli.main(["--repo", str(repo), "init"]) == 1

    assert subjects(journal_dir) == ["init: 2 Issues aus bd export"]
    assert (journal_dir / MARKER).is_file()
    stored = (journal_dir / "issues" / "t-2.json").read_text()
    assert stored == normalized(issue("t-2"))
    assert git(journal_dir, "log", "-1", "--format=%an <%ae>") == (
        "Journal Test <journal@test.invalid>\n"
    )
    assert git(journal_dir, "status", "--porcelain") == ""
    assert "bereits eingerichtet" in capsys.readouterr().err


def test_init_keeps_only_fields_the_hooks_deliver(
    monkeypatch, tmp_path, repo
):
    row = {
        "_type": "issue",
        **issue(labels=["probe"]),
        "comments": [{"text": SECRET}],
        "comment_count": 1,
        "dependency_count": 0,
        "dependent_count": 0,
    }
    fake_bd(tmp_path, monkeypatch, [row])

    assert cli.main(["--repo", str(repo), "init"]) == 0

    stored = repo / ".local" / "beads-journal" / "issues" / "t-1.json"
    assert stored.read_text() == normalized(issue(labels=["probe"]))


def test_init_refuses_leftover_folder(
    monkeypatch, tmp_path, repo, capsys
):
    fake_bd(tmp_path, monkeypatch, [])
    leftover = repo / ".local" / "beads-journal"
    leftover.mkdir(parents=True)
    (leftover / "rest").write_text("")

    assert cli.main(["--repo", str(repo), "init"]) == 1

    assert "nicht leer" in capsys.readouterr().err
    assert not (leftover / MARKER).exists()


def test_init_rejects_non_issue_export_rows(
    monkeypatch, tmp_path, repo
):
    fake_bd(tmp_path, monkeypatch, [{"_type": "memory", "key": SECRET}])

    assert cli.main(["--repo", str(repo), "init"]) == 1

    assert not (repo / ".local" / "beads-journal").exists()


def test_init_path_is_stored_relative_to_repo(
    monkeypatch, tmp_path, repo
):
    fake_bd(tmp_path, monkeypatch, [])
    target = repo / "journal"

    assert (
        cli.main(["--repo", str(repo), "init", "--path", str(target)])
        == 0
    )
    assert call_hook(monkeypatch, repo, "create", issue()) == 0

    assert (
        git(repo, "config", "--get", cli.CONFIG_KEY).strip()
        == "journal"
    )
    assert subjects(target)[-1] == "create t-1: Titel t-1 [open]"


def test_status_reports_active_journal(
    monkeypatch, repo, journal_dir, capsys
):
    call_hook(monkeypatch, repo, "update", issue(), "t-2")
    capsys.readouterr()

    assert cli.main(["--repo", str(repo), "status"]) == 0

    output = capsys.readouterr().out
    assert "Zustand: aktiv" in output
    assert "Commits: 1" in output
    assert f"Fehler in {ERRORS_LOG}: 1" in output


def test_shell_hook_runs_journal_and_local_addition(repo, journal_dir):
    hooks = repo / ".beads" / "hooks"
    hooks.mkdir(parents=True)
    for name in ("beads-journal", "on_update"):
        (hooks / name).write_bytes(
            (ROOT / ".beads" / "hooks" / name).read_bytes()
        )
        (hooks / name).chmod(0o755)
    (repo / ".venv").symlink_to(ROOT / ".venv")
    (repo / "src").symlink_to(ROOT / "src")
    local_hook = hooks / "on_update.local"
    local_hook.write_text(
        '#!/bin/sh\ncat > "$(dirname "$0")/seen-$1-$2"\n'
    )
    local_hook.chmod(0o755)
    payload = json.dumps(issue())

    result = subprocess.run(
        [str(hooks / "on_update"), "t-1", "update"],
        input=payload,
        text=True,
        cwd=ROOT / "tests",
        timeout=30,
    )

    assert result.returncode == 0
    assert subjects(journal_dir)[-1] == "update t-1: Titel t-1 [open]"
    assert (hooks / "seen-t-1-update").read_text() == payload


@pytest.mark.parametrize("existing", [False, True])
def test_failed_commit_does_not_leak_into_next_event(
    monkeypatch, repo, journal_dir, existing
):
    if existing:
        assert call_hook(monkeypatch, repo, "create", issue()) == 0
    before = subjects(journal_dir)
    real_git = journal.run_git

    def fail_commit(directory, *args):
        if args[0] == "commit":
            raise GitError("git commit: Exit 1")
        return real_git(directory, *args)

    monkeypatch.setattr(journal, "run_git", fail_commit)
    assert (
        call_hook(monkeypatch, repo, "update", issue(title=SECRET)) == 1
    )
    assert subjects(journal_dir) == before
    assert git(journal_dir, "status", "--porcelain") == ""
    assert (
        "git commit: Exit 1" in (journal_dir / ERRORS_LOG).read_text()
    )
    assert SECRET not in (journal_dir / ERRORS_LOG).read_text()

    monkeypatch.setattr(journal, "run_git", real_git)
    assert call_hook(monkeypatch, repo, "create", issue("t-2")) == 0
    assert (
        git(
            journal_dir, "show", "--format=", "--name-only", "HEAD"
        ).strip()
        == "issues/t-2.json"
    )


def test_failed_init_does_not_activate_journal(monkeypatch, repo):
    real_git = journal.run_git

    def fail_commit(directory, *args):
        if args[0] == "commit":
            raise GitError("git commit: Exit 1")
        return real_git(directory, *args)

    monkeypatch.setattr(journal, "run_git", fail_commit)
    path = repo / ".local/beads-journal"
    with pytest.raises(GitError):
        journal.initialize(path, [], IDENTITY)
    assert not (path / MARKER).exists()
    assert call_hook(monkeypatch, repo, "create", issue()) == 0


def test_write_error_is_sanitized(
    monkeypatch, repo, journal_dir, capsys
):
    def fail_replace(*_args):
        raise OSError(13, SECRET)

    monkeypatch.setattr(journal.os, "replace", fail_replace)
    assert call_hook(monkeypatch, repo, "create", issue()) == 1
    assert (
        "Dateizugriff fehlgeschlagen"
        in (journal_dir / ERRORS_LOG).read_text()
    )
    assert SECRET not in capsys.readouterr().err
    assert list((journal_dir / "issues").iterdir()) == []
    assert len(subjects(journal_dir)) == 1


def test_corrupt_stored_issue_logs_without_raw_values(
    monkeypatch, repo, journal_dir
):
    assert call_hook(monkeypatch, repo, "create", issue()) == 0
    (journal_dir / "issues/t-1.json").write_text(SECRET)
    assert call_hook(monkeypatch, repo, "update", issue()) == 1
    log = (journal_dir / ERRORS_LOG).read_text()
    assert "gespeichertes Issue: kein JSON" in log
    assert SECRET not in log
    assert len(subjects(journal_dir)) == 2
