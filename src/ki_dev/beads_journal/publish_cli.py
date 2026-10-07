"""Befehle audit und index: I/O-Rand der öffentlichen PM-Sicht.

audit liest alle Revisionen (Commit-Nachrichten und eingefügte Zeilen)
und meldet Privatbefunde nur als Revision/Datei/Kategorie. index
schreibt index.md aus issues/*.json, gleicht gegen bd export ab und
committet sie unter der Journal-Sperre. Die Datenbank bleibt
unverändert; nichts wird gepusht oder zurückimportiert.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path

from ki_dev.beads_journal.git import run_git
from ki_dev.beads_journal.journal import (
    ISSUES,
    NO_AUTO_MAINTENANCE,
    JournalError,
    is_active,
    locked,
)
from ki_dev.beads_journal.publish import (
    INDEX,
    Finding,
    audit_changes,
    orphans,
    render_index,
)

COMMIT_MESSAGE = "<Commit-Nachricht>"
_RECORD = "\x1e"
_FIELD = "\x1f"


def run_audit(journal: Path) -> int:
    """0 ohne Befunde, 1 mit Befunden (Entscheidung beim Menschen)."""
    _require_active(journal)
    findings = audit_changes(
        [*_commit_messages(journal), *_added_lines(journal)]
    )
    for finding in findings:
        print(_finding_line(finding))
    revisions = len({finding.revision for finding in findings})
    print(
        f"{len(findings)} Befunde in {revisions} Revisionen"
        if findings
        else "keine Privatbefunde"
    )
    return 1 if findings else 0


def run_index(
    root: Path,
    journal: Path,
    export_issues: Callable[[Path], list[dict]],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """index.md schreiben und als eigenen Commit festhalten."""
    _require_active(journal)
    db_ids = [issue["id"] for issue in export_issues(root)]
    exported_at = now().strftime("%Y-%m-%dT%H:%M:%SZ")
    _, head = run_git(root, "rev-parse", "--short=12", "HEAD")
    issues = _journal_issues(journal)
    missing = orphans((issue["id"] for issue in issues), db_ids)
    text = render_index(issues, missing, exported_at, head.strip())
    with locked(journal):
        _write_index(journal, text)
        _commit_index(journal, exported_at)
    print(
        f"{journal / INDEX}: {len(issues)} Vorgänge, "
        f"{len(missing)} nicht in DB"
    )
    return 0


def _require_active(journal: Path) -> None:
    if not is_active(journal):
        raise JournalError(
            f"{journal}: nicht eingerichtet (kein Marker)"
        )


def _commit_messages(journal: Path) -> Iterator[tuple[str, str, str]]:
    _, stdout = run_git(
        journal, "log", "--all", f"--format=%H{_FIELD}%B{_RECORD}"
    )
    for record in stdout.split(_RECORD):
        revision, _, message = record.strip("\n").partition(_FIELD)
        if revision:
            yield revision, COMMIT_MESSAGE, message


def _added_lines(journal: Path) -> Iterator[tuple[str, str, str]]:
    """Je Revision und Datei die eingefügten Zeilen; alles, was je im
    Journal stand, kam über eine solche Zeile hinein."""
    _, stdout = run_git(
        journal,
        "log",
        "--all",
        "-p",
        "--no-color",
        "--no-ext-diff",
        "--unified=0",
        f"--format={_RECORD}%H",
    )
    for record in stdout.split(_RECORD):
        revision, _, patch = record.partition("\n")
        if revision:
            yield from _patch_files(revision.strip(), patch)


def _patch_files(
    revision: str, patch: str
) -> Iterator[tuple[str, str, str]]:
    path, added = None, []
    for line in patch.splitlines():
        if line.startswith("+++ "):
            if path is not None:
                yield revision, path, "\n".join(added)
            path = line[4:].removeprefix("b/")
            added = []
        elif line.startswith("+") and path is not None:
            added.append(line[1:])
    if path is not None:
        yield revision, path, "\n".join(added)


def _finding_line(finding: Finding) -> str:
    return f"{finding.revision[:10]} {finding.path} {finding.category}"


def _journal_issues(journal: Path) -> list[dict]:
    issues = []
    for path in sorted((journal / ISSUES).glob("*.json")):
        try:
            issue = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            raise JournalError(
                f"{ISSUES}/{path.name}: nicht lesbar "
                f"({type(exc).__name__})"
            ) from None
        if not isinstance(issue, dict) or issue.get("id") != path.stem:
            raise JournalError(
                f"{ISSUES}/{path.name}: id passt nicht zum Dateinamen"
            )
        issues.append(issue)
    return issues


def _write_index(journal: Path, text: str) -> None:
    target = journal / INDEX
    temporary = journal / f".{INDEX}.tmp"
    try:
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def _commit_index(journal: Path, exported_at: str) -> None:
    """Eigener Commit nur bei geänderter Datei (gleiche Eingabe ergibt
    dieselbe index.md und damit keinen leeren Commit)."""
    run_git(journal, "add", "--", INDEX)
    code, _ = run_git(
        journal,
        "diff",
        "--cached",
        "--quiet",
        "--",
        INDEX,
        retcode=(0, 1),
    )
    if code == 0:
        return
    run_git(
        journal,
        "commit",
        "--no-verify",
        "-q",
        "-m",
        f"index: Stand {exported_at}",
        "--",
        INDEX,
        config=NO_AUTO_MAINTENANCE,
    )
