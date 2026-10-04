"""Beads-Journal: Hook-Aufrufe gegen ein Journal in tmp_path."""

import io
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from ki_dev.beads_journal import cli, drain, journal, queue
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


def trailers(directory):
    """Journal-Event-Trailer je Commit, älteste zuerst ("" ohne)."""
    output = git(
        directory,
        "log",
        "--format=%(trailers:key=Journal-Event,valueonly)%x00",
    )
    return [part.strip() for part in output.split("\0")[:-1]][::-1]


def queue_state(journal_dir):
    with queue.opened(journal_dir) as connection:
        return (
            queue.pending_count(connection),
            queue.failed_entries(connection),
        )


@contextmanager
def held_lock(journal_dir):
    """Hält die Journal-Sperre in einem fremden Prozess."""
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
        yield
    finally:
        holder.communicate("", timeout=10)


def git_wrapper(tmp_path, body):
    """PATH-Ordner mit einem git, das body vor dem echten git ausführt.

    body sieht die Argumente von run_git: $1=-C, $2=Journal, $3=Befehl.
    """
    folder = tmp_path / "bin"
    folder.mkdir()
    wrapper = folder / "git"
    wrapper.write_text(
        f'#!/bin/sh\n{body}\nexec {shutil.which("git")} "$@"\n'
    )
    wrapper.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{folder}{os.pathsep}{os.environ['PATH']}",
        "PYTHONPATH": str(ROOT / "src"),
    }


def drain_process(journal_dir, prelude="pass", env=None):
    """drain in eigenem Prozess; prelude kann Funktionen ersetzen."""
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import os, sys; from pathlib import Path;"
            "from ki_dev.beads_journal import drain, queue;"
            f"{prelude};"
            "drain.drain(Path(sys.argv[1]))",
            str(journal_dir),
        ],
        env=env or {**os.environ, "PYTHONPATH": str(ROOT / "src")},
        timeout=30,
        check=False,
    )


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


def hook_process(repo, event, payload, env=None):
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
        env=env or {**os.environ, "PYTHONPATH": str(ROOT / "src")},
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
    assert trailers(journal_dir) == ["", "1", "2", "3"]
    assert queue_state(journal_dir) == (0, [])


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


def test_busy_lock_keeps_event_for_next_drain_in_queue_order(
    monkeypatch, repo, journal_dir
):
    """Prüffälle 1 und 7: A wartet in der Queue, B committet A und B."""
    monkeypatch.setattr(journal, "LOCK_TIMEOUT", 0.2)
    with held_lock(journal_dir):
        assert call_hook(monkeypatch, repo, "create", issue("t-a")) == 0
        assert subjects(journal_dir) == ["init: 0 Issues aus bd export"]
        assert queue_state(journal_dir) == (1, [])

    assert call_hook(monkeypatch, repo, "create", issue("t-b")) == 0

    assert subjects(journal_dir)[1:] == [
        "create t-a: Titel t-a [open]",
        "create t-b: Titel t-b [open]",
    ]
    assert trailers(journal_dir)[1:] == ["1", "2"]
    assert queue_state(journal_dir) == (0, [])
    assert not (journal_dir / ERRORS_LOG).exists()


def test_parallel_hooks_with_slow_git_lose_no_event(
    tmp_path, repo, journal_dir
):
    """Prüffall 2: Wartende geben nach 5 s auf, der Halter committet."""
    env = git_wrapper(tmp_path, "sleep 0.4")
    payloads = [issue(f"t-{number}") for number in range(5)]
    processes = [
        hook_process(repo, "create", payload, env)
        for payload in payloads
    ]
    for process, payload in zip(processes, payloads, strict=True):
        process.stdin.write(json.dumps(payload).encode())
        process.stdin.close()
    for process in processes:
        process.wait(timeout=60)

    assert [process.returncode for process in processes] == [0] * 5
    assert sorted(subjects(journal_dir)[1:]) == sorted(
        f"create t-{number}: Titel t-{number} [open]"
        for number in range(5)
    )
    assert sorted(trailers(journal_dir)[1:]) == [
        "1",
        "2",
        "3",
        "4",
        "5",
    ]
    assert queue_state(journal_dir) == (0, [])


def test_kill_between_commit_and_ack_gives_no_second_commit(
    journal_dir,
):
    """Prüffall 3."""
    drain.enqueue(journal_dir, "create", issue())

    killed = drain_process(
        journal_dir, "queue.ack = lambda *_args: os._exit(9)"
    )

    assert killed.returncode == 9
    assert trailers(journal_dir)[1:] == ["1"]
    assert queue_state(journal_dir) == (1, [])

    assert drain.drain(journal_dir) == drain.DrainResult(0, 0)
    assert subjects(journal_dir)[1:] == ["create t-1: Titel t-1 [open]"]
    assert queue_state(journal_dir) == (0, [])


def test_kill_during_git_commit_is_committed_once(
    tmp_path, journal_dir
):
    """Prüffall 4: verwaiste index.lock, unbestätigter Eintrag."""
    env = git_wrapper(
        tmp_path,
        'if [ "$3" = commit ]; then\n'
        '  touch "$2/.git/index.lock"; kill -9 "$PPID"; exit 1\n'
        "fi",
    )
    drain.enqueue(journal_dir, "create", issue())

    killed = drain_process(journal_dir, env=env)

    assert killed.returncode == -9
    assert (journal_dir / ".git" / "index.lock").exists()
    assert len(subjects(journal_dir)) == 1

    assert drain.drain(journal_dir) == drain.DrainResult(1, 0)
    assert subjects(journal_dir)[1:] == ["create t-1: Titel t-1 [open]"]
    assert trailers(journal_dir)[1:] == ["1"]
    assert not (journal_dir / ".git" / "index.lock").exists()
    assert git(journal_dir, "status", "--porcelain") == ""
    assert (
        "verwaiste .git/index.lock entfernt"
        in (journal_dir / ERRORS_LOG).read_text()
    )


def test_trailer_match_is_exact(monkeypatch, repo, journal_dir):
    """Prüffall 5: Ereignis 10 committet, 1 gilt nicht als erledigt."""
    git(
        journal_dir,
        "commit",
        "--allow-empty",
        "-q",
        "-m",
        "fremd",
        "--trailer",
        "Journal-Event: 10",
    )

    assert call_hook(monkeypatch, repo, "create", issue()) == 0

    assert subjects(journal_dir)[-1] == "create t-1: Titel t-1 [open]"
    assert trailers(journal_dir)[-2:] == ["10", "1"]


def test_queue_ids_are_not_reused_after_ack(journal_dir):
    first = drain.enqueue(journal_dir, "create", issue())
    drain.drain(journal_dir)

    assert drain.enqueue(journal_dir, "update", issue()) > first


def test_concurrent_first_open_creates_queue_once(tmp_path):
    """Rauchtest der atomaren Erstanlage (queue._create).

    Das Wettrennen um PRAGMA journal_mode=WAL tritt nur selten auf;
    dieser Test fängt eine Regression deshalb nicht verlässlich, er
    prüft nur, dass gleichzeitige Erstöffnungen gelingen, die Tabelle
    vorhanden ist und keine temporären Dateien zurückbleiben.
    """
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    script = (
        "import sys; from pathlib import Path;"
        "from ki_dev.beads_journal import queue;"
        "handle_ctx = queue.opened(Path(sys.argv[1]));"
        "handle = handle_ctx.__enter__();"
        "queue.put(handle, 'create', {'id': 't-1'});"
        "handle_ctx.__exit__(None, None, None)"
    )
    for attempt in range(3):
        folder = tmp_path / f"q{attempt}"
        folder.mkdir()
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", script, str(folder)], env=env
            )
            for _ in range(8)
        ]
        assert [process.wait(timeout=30) for process in processes] == [
            0
        ] * 8
        # -wal/-shm dürfen bleiben: Manche SQLite-Builds (macOS-Host)
        # entfernen sie beim Schließen nicht. Temporäre Dateien nicht.
        names = {path.name for path in folder.iterdir()}
        assert queue.QUEUE_FILE in names
        assert names <= {
            queue.QUEUE_FILE,
            f"{queue.QUEUE_FILE}-wal",
            f"{queue.QUEUE_FILE}-shm",
        }
        with queue.opened(folder) as handle:
            assert queue.pending_count(handle) == 8


def test_drain_command_commits_waiting_entries(
    repo, journal_dir, capsys
):
    drain.enqueue(journal_dir, "create", issue())

    assert cli.main(["--repo", str(repo), "drain"]) == 0

    assert "Abgearbeitet: 1 Commits" in capsys.readouterr().out
    assert subjects(journal_dir)[-1] == "create t-1: Titel t-1 [open]"


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
    monkeypatch, repo, journal_dir, payload, hook_id, reason, capsys
):
    """Prüffall 6: fehlgeschlagen vermerkt und in status sichtbar."""
    assert call_hook(monkeypatch, repo, "update", payload, hook_id) == 1

    assert subjects(journal_dir) == ["init: 0 Issues aus bd export"]
    log = (journal_dir / ERRORS_LOG).read_text()
    assert reason in log
    assert SECRET not in log
    assert list((journal_dir / "issues").iterdir()) == []
    capsys.readouterr()
    assert cli.main(["--repo", str(repo), "status"]) == 0
    output = capsys.readouterr().out
    assert "Warteschlange: 0 offen" in output
    assert "Fehlgeschlagen: 1" in output
    shown_id = "?" if "/" in hook_id else hook_id
    assert f"#1 update {shown_id}: {reason}" in output
    assert SECRET not in output
    stored = (journal_dir / queue.QUEUE_FILE).read_bytes()
    assert SECRET.encode() not in stored


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
