"""Befehle des Beads-Journals: init, hook, drain, status, audit, index,
comments.

argparse statt typer: der Hook startet je bd-Ereignis neu und hat 10 s
Frist. Ort des Journals: git config ki-dev.beadsJournal im Projekt-Repo
(relativ zum Repo oder absolut), sonst <repo>/.local/beads-journal.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from plumbum import local
from plumbum.commands.processes import (
    CommandNotFound,
    ProcessExecutionError,
    ProcessTimedOut,
)

from ki_dev.beads_journal import comments, queue
from ki_dev.beads_journal.contract import (
    EVENTS,
    PayloadError,
    check_event,
    check_issue,
    is_issue_id,
)
from ki_dev.beads_journal.drain import (
    DrainStopped,
    drain,
    enqueue,
    record_invalid,
)
from ki_dev.beads_journal.git import GitError, run_git
from ki_dev.beads_journal.journal import (
    ERRORS_LOG,
    JournalError,
    LockBusy,
    initialize,
    io_error,
    is_active,
    log_error,
)
from ki_dev.beads_journal.publish_cli import run_audit, run_index

CONFIG_KEY = "ki-dev.beadsJournal"
DEFAULT_LOCATION = Path(".local/beads-journal")
BD_PROGRAM = "bd"
EXPORT_TIMEOUT = 60
IDENTITY_KEYS = ("user.name", "user.email")
# Nur bd export liefert diese Felder, die Hook-Nutzlast nicht. Ohne sie
# entspricht der Erststand der Hook-Form: das erste Ereignis zeigt keine
# Scheinlöschungen, und Kommentartexte gelangen nicht ins Journal.
EXPORT_ONLY_FIELDS = (
    "comments",
    "comment_count",
    "dependency_count",
    "dependent_count",
)
_EXPECTED = (PayloadError, JournalError, GitError, queue.QueueError)


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    repo = arguments.repo or Path.cwd()
    if arguments.command == "hook":
        return run_hook(repo, arguments.issue_id, arguments.event)
    if arguments.command == "init":
        return run_init(repo, arguments.path)
    if arguments.command == "drain":
        return run_drain(repo)
    if arguments.command in ("audit", "index"):
        return _run_publish(repo, arguments.command)
    if arguments.command == "comments":
        return _run_comments(repo, arguments)
    return run_status(repo)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m ki_dev.beads_journal",
        description="Beads-Journal: je bd-Ereignis ein Commit in ein "
        "lokales Git-Repo.",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        help="Projekt-Repo (Vorgabe: aktueller Ordner)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser(
        "init", help="Journal anlegen und aus bd export befüllen"
    )
    init.add_argument(
        "--path",
        type=Path,
        help=f"Ort des Journals; landet in git config {CONFIG_KEY}",
    )
    hook = commands.add_parser(
        "hook", help="ein bd-Ereignis committen (Issue-JSON auf stdin)"
    )
    hook.add_argument("issue_id")
    hook.add_argument("event")
    commands.add_parser(
        "drain", help="Warteschlange abarbeiten (Wiederanlauf)"
    )
    commands.add_parser(
        "status",
        help="Warteschlange abarbeiten, dann Ort, Zustand, offene und "
        "fehlgeschlagene Einträge zeigen",
    )
    commands.add_parser(
        "audit",
        help="alle Revisionen auf Privatbefunde prüfen (nur "
        "Revision/Datei/Kategorie; Exit 1 bei Befunden)",
    )
    commands.add_parser(
        "index",
        help="index.md aus issues/*.json schreiben, gegen bd export "
        "abgleichen und committen",
    )
    comments.add_parser(commands)
    return parser


def _run_publish(repo: Path, command: str) -> int:
    """audit/index: öffentliche PM-Sicht prüfen bzw. erzeugen."""
    try:
        root = repo_root(repo)
        journal = journal_path(root)
        if command == "audit":
            return run_audit(journal)
        return run_index(root, journal, export_issues)
    except _EXPECTED as exc:
        return _fail(exc)
    except OSError as exc:
        return _fail(io_error(exc))


def _run_comments(repo: Path, arguments: argparse.Namespace) -> int:
    """comments export/mark-incorporated/lint (Kommentar-Journal)."""
    try:
        root = repo_root(repo)
        return comments.run(
            root, journal_path(root), arguments, export_rows
        )
    except _EXPECTED as exc:
        return _fail(exc)
    except OSError as exc:
        return _fail(io_error(exc))


def run_hook(repo: Path, issue_id: str, event: str) -> int:
    """Ohne Marker sofort 0 (Klon ohne Journal); Fehler ins Log.

    Gültige Ereignisse landen zuerst in der Warteschlange, ungültige
    dort als fehlgeschlagen. Belegte Sperre ist kein Fehler: Der Halter
    oder der nächste drain committet den Eintrag.
    """
    try:
        journal = journal_path(repo)
    except GitError as exc:
        return _fail(exc)
    if not is_active(journal):
        return 0
    safe_event = event if event in EVENTS else "?"
    safe_id = issue_id if is_issue_id(issue_id) else "?"
    try:
        issue = _read_payload()
        check_event(event, issue_id, issue)
    except PayloadError as exc:
        reason = str(exc)
        _report(
            journal,
            safe_event,
            safe_id,
            lambda: record_invalid(
                journal, safe_event, safe_id, reason
            ),
        )
        return _fail(exc)
    return _report(
        journal,
        safe_event,
        safe_id,
        lambda: _enqueue_and_drain(journal, event, issue),
    )


def _enqueue_and_drain(journal: Path, event: str, issue: dict) -> None:
    enqueue(journal, event, issue)
    try:
        result = drain(journal)
    except LockBusy as exc:
        print(
            f"beads-journal: {exc}; Ereignis bleibt in der "
            "Warteschlange",
            file=sys.stderr,
        )
        return
    if result.failed:
        # Grund steht schon je Eintrag im Log.
        raise DrainStopped(_failed_text(result.failed))


def _report(
    journal: Path, event: str, issue_id: str, action: Callable[[], None]
) -> int:
    """Führt action aus; Fehler ins Log und Exit 1.

    DrainStopped hat seinen Grund schon beim betroffenen Eintrag
    protokolliert.
    """
    try:
        action()
    except DrainStopped as exc:
        return _fail(exc)
    except (*_EXPECTED, OSError) as exc:
        failure = io_error(exc) if isinstance(exc, OSError) else exc
        return _hook_error(journal, event, issue_id, failure)
    return 0


def _hook_error(
    journal: Path, event: str, issue_id: str, error: Exception
) -> int:
    try:
        log_error(journal, event, issue_id, str(error))
    except OSError as exc:
        _fail(io_error(exc))
    return _fail(error)


def run_init(repo: Path, path: Path | None) -> int:
    """Richtet ein; ein bestehendes Journal wird nur abgearbeitet."""
    try:
        root = repo_root(repo)
        journal = path.resolve() if path else journal_path(repo)
        print(_initialize_once(root, journal))
        if path:
            store_location(root, journal)
    except _EXPECTED as exc:
        print(
            f"beads-journal: init fehlgeschlagen: {exc}",
            file=sys.stderr,
        )
        return 1
    except OSError as exc:
        return _fail(io_error(exc))
    return _guarded_drain(journal)


def _initialize_once(root: Path, journal: Path) -> str:
    if is_active(journal):
        return f"Beads-Journal bereits eingerichtet: {journal}"
    issues = export_issues(root)
    initialize(journal, issues, read_identity(root))
    return (
        f"Beads-Journal eingerichtet: {journal} ({len(issues)} Issues)"
    )


def run_drain(repo: Path) -> int:
    try:
        journal = journal_path(repo)
    except GitError as exc:
        return _fail(exc)
    if not is_active(journal):
        print(f"{journal}: nicht eingerichtet (kein Marker)")
        return 0
    return _guarded_drain(journal)


def run_status(repo: Path) -> int:
    """Arbeitet zuerst die Warteschlange ab, dann die Übersicht."""
    try:
        journal = journal_path(repo)
    except GitError as exc:
        return _fail(exc)
    print(f"Ort: {journal}")
    if not is_active(journal):
        print("Zustand: nicht eingerichtet (kein Marker)")
        return 0
    drained = _guarded_drain(journal)
    try:
        _print_status(journal)
    except (GitError, queue.QueueError) as exc:
        return _fail(exc)
    return drained


def _print_status(journal: Path) -> None:
    _, count = run_git(journal, "rev-list", "--count", "HEAD")
    _, last = run_git(
        journal, "log", "-1", "--format=%ad %s", "--date=iso"
    )
    with queue.opened(journal) as handle:
        pending = queue.pending_count(handle)
        failed = queue.failed_entries(handle)
    print("Zustand: aktiv")
    print(f"Commits: {count.strip()}")
    print(f"Letzter: {last.strip()}")
    print(f"Warteschlange: {pending} offen")
    print(f"Fehlgeschlagen: {len(failed)}")
    for entry in failed:
        print(
            f"  #{entry.queue_id} {entry.event} {entry.issue_id}: "
            f"{entry.reason}"
        )
    print(
        f"Fehler in {ERRORS_LOG}: {_count_lines(journal / ERRORS_LOG)}"
    )


def _guarded_drain(journal: Path) -> int:
    """drain für init, drain, status; belegte Sperre ist kein Fehler."""
    try:
        result = drain(journal)
    except LockBusy as exc:
        print(f"Abarbeiten: {exc}; Einträge bleiben in der Queue")
        return 0
    except (DrainStopped, GitError, queue.QueueError, OSError) as exc:
        return _fail(io_error(exc) if isinstance(exc, OSError) else exc)
    print(f"Abgearbeitet: {result.committed} Commits")
    if not result.failed:
        return 0
    return _fail(DrainStopped(_failed_text(result.failed)))


def _failed_text(count: int) -> str:
    return f"{count} Einträge fehlgeschlagen; Gründe in {ERRORS_LOG}"


def repo_root(repo: Path) -> Path:
    _, stdout = run_git(repo, "rev-parse", "--show-toplevel")
    return Path(stdout.strip())


def journal_path(repo: Path) -> Path:
    root = repo_root(repo)
    code, stdout = run_git(
        root, "config", "--local", "--get", CONFIG_KEY, retcode=(0, 1)
    )
    configured = Path(stdout.strip()) if code == 0 else DEFAULT_LOCATION
    return root / configured


def store_location(root: Path, journal: Path) -> None:
    """Speichert den Ort relativ zum Repo, wenn er darin liegt.

    So gilt derselbe Wert auf dem Host und unter /workspace im
    Container.
    """
    try:
        value = journal.relative_to(root.resolve())
    except ValueError:
        value = journal
    run_git(root, "config", "--local", CONFIG_KEY, str(value))


def read_identity(root: Path) -> dict[str, str]:
    """Git-Identität des Projekt-Repos für die Commits im Journal."""
    identity = {}
    for key in IDENTITY_KEYS:
        code, stdout = run_git(
            root, "config", "--get", key, retcode=(0, 1)
        )
        if code == 0:
            identity[key] = stdout.strip()
    return identity


def export_issues(root: Path) -> list[dict]:
    """bd export in Hook-Form: ohne EXPORT_ONLY_FIELDS."""
    rows = export_rows(root)
    for row in rows:
        for field in EXPORT_ONLY_FIELDS:
            row.pop(field, None)
    return rows


def export_rows(root: Path) -> list[dict]:
    """bd export ohne Memories und Infrastruktur; jede Zeile geprüft."""
    try:
        with local.cwd(root):
            _, stdout, _ = local[BD_PROGRAM][
                "--readonly", "export"
            ].run(retcode=0, timeout=EXPORT_TIMEOUT)
    except CommandNotFound as exc:
        raise JournalError("bd nicht gefunden") from exc
    except ProcessTimedOut as exc:
        raise JournalError(
            f"bd export: über {EXPORT_TIMEOUT} s"
        ) from exc
    except ProcessExecutionError as exc:
        raise JournalError(f"bd export: Exit {exc.retcode}") from exc
    return [
        _export_row(line, number)
        for number, line in enumerate(stdout.splitlines(), start=1)
        if line.strip()
    ]


def _export_row(line: str, number: int) -> dict:
    label = f"bd export Zeile {number}"
    try:
        row = json.loads(line)
    except json.JSONDecodeError as exc:
        raise PayloadError(f"{label}: kein JSON") from exc
    if (
        not isinstance(row, dict)
        or row.pop("_type", "issue") != "issue"
    ):
        raise PayloadError(f"{label}: kein Issue-Datensatz")
    check_issue(row, [label])
    return row


def _read_payload() -> object:
    try:
        return json.loads(sys.stdin.buffer.read())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PayloadError("Nutzlast: kein JSON") from exc


def _count_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8") as lines:
        return sum(1 for _ in lines)


def _fail(error: Exception) -> int:
    print(f"beads-journal: {error}", file=sys.stderr)
    return 1
