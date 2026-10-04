"""Journal-Repo: Issue-Dateien schreiben und je Ereignis committen.

Alle Schreibzugriffe laufen unter einer flock-Sperre auf
<journal>/.lock; das Betriebssystem gibt sie frei, wenn bd den Hook nach
seiner Frist tötet. Commits folgen der Reihenfolge des Sperrerwerbs.
Eine verspätete Nutzlast (updated_at in ganzen Sekunden älter als in
der Datei) überschreibt nichts und ergibt einen leeren Commit mit
Vermerk.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock, Timeout

from ki_dev.beads_journal.contract import PayloadError, check_issue
from ki_dev.beads_journal.git import GitError, run_git
from ki_dev.beads_journal.timestamps import timestamp

MARKER = ".beads-journal"
ISSUES = "issues"
LOCK = ".lock"
ERRORS_LOG = ".errors.log"
LOCK_TIMEOUT = 5
_GITIGNORE = f"{LOCK}\n{ERRORS_LOG}\n{ISSUES}/.*.tmp\n"
_MARKER_TEXT = "Beads-Journal von ki-dev; siehe README.md.\n"
_README = """\
# Beads-Journal

Je Änderung an einem Beads-Vorgang ein Commit, geschrieben von den
bd-Hooks on_create, on_update und on_close. `issues/<ID>.json` enthält
die letzte Hook-Nutzlast des Vorgangs. Löschungen und Kommentartexte
fehlen.

Commit-Nachricht: `<Ereignis> <ID>: <Titel> [<Status>]`; ` (verspätet)`
markiert eine ältere Nutzlast, die die Datei nicht überschrieben hat.

```bash
# offene Vorgänge als Tabelle
jq -r 'select(.status != "closed") | [.id, .status, .title] | @tsv' \\
  issues/*.json

# Verlauf eines Vorgangs
git log -p -- issues/<ID>.json

# Ereignisse der letzten Woche
git log --since=1.week --format='%ad %s' --date=short
```

Einrichtung im Projekt-Repo: `python -m ki_dev.beads_journal init`
(optional `--path P`); `status` zeigt Ort, Commits und Fehlerzahl.
Ohne `.beads-journal` bleibt der Hook inaktiv.

Hooks laufen asynchron; die Commit-Reihenfolge folgt dem Sperrerwerb.
"Verspätet" zählt in ganzen Sekunden von `updated_at`; innerhalb
derselben Sekunde bleiben Vertauschungen unerkannt.
Ungültige Nutzlasten, Git-Fehler und Sperr-Timeouts (5 s) verwerfen
das Ereignis und erscheinen in `.errors.log`. Wiederanlauf und
Verlustfreiheit folgen erst mit ki-dev-ablauf-yl5.1. bd beendet Hooks
nach 10 s; ein erzwungener Abbruch kann deshalb auch die
Fehlerdiagnose verhindern.

Kein gleichzeitiger bd-Betrieb auf Host und Container: flock-Sperren
über virtiofs sind dafür unzuverlässig. Keine manuellen
Git-Schreibzugriffe im Journal, solange Hooks laufen können. Das
Journal wird lokal geführt; ein Push ist ein getrennter Schritt.
"""


class JournalError(RuntimeError):
    """Journal nicht beschreibbar: Sperre fehlt oder Ordner belegt."""


def is_active(journal: Path) -> bool:
    return (journal / MARKER).is_file()


def record_event(journal: Path, event: str, issue: dict) -> None:
    """Schreibt issues/<ID>.json und committet unter der Sperre."""
    with _locked(journal):
        _commit_event(journal, event, issue)


def initialize(
    journal: Path, issues: list[dict], identity: dict[str, str]
) -> None:
    """Legt das Journal an und committet einmalig den bd-Export.

    identity sind git-config-Schlüssel (user.name, user.email) für die
    Commits im Journal; der Marker entsteht zuletzt im selben Commit.
    """
    if is_active(journal):
        raise JournalError(f"{journal} ist bereits eingerichtet")
    if journal.exists() and any(journal.iterdir()):
        raise JournalError(
            f"{journal} ist nicht leer (Rest eines Abbruchs?); "
            "leeren oder anderen --path wählen"
        )
    (journal / ISSUES).mkdir(parents=True, exist_ok=True)
    with _locked(journal):
        run_git(journal, "init", "-q", "-b", "main")
        for key, value in identity.items():
            run_git(journal, "config", key, value)
        (journal / ".gitignore").write_text(
            _GITIGNORE, encoding="utf-8"
        )
        (journal / "README.md").write_text(_README, encoding="utf-8")
        for issue in issues:
            _write_atomic(
                _issue_file(journal, issue["id"]), _normalize(issue)
            )
        (journal / MARKER).write_text(_MARKER_TEXT, encoding="utf-8")
        try:
            run_git(journal, "add", "-A")
            run_git(
                journal,
                "commit",
                "--no-verify",
                "-q",
                "-m",
                f"init: {len(issues)} Issues aus bd export",
            )
        except (GitError, OSError):
            (journal / MARKER).unlink()
            raise


def log_error(
    journal: Path, event: str, issue_id: str, reason: str
) -> None:
    """Hängt eine Zeile an .errors.log; ohne Rohwerte der Nutzlast."""
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    line = f"{stamp} {event} {issue_id}: {reason}\n"
    with (journal / ERRORS_LOG).open("a", encoding="utf-8") as log:
        log.write(line)


@contextmanager
def _locked(journal: Path) -> Iterator[None]:
    lock = FileLock(journal / LOCK, timeout=LOCK_TIMEOUT)
    try:
        lock.acquire()
    except Timeout as exc:
        raise JournalError(
            f"Sperre nicht binnen {LOCK_TIMEOUT} s erhalten"
        ) from exc
    try:
        yield
    finally:
        lock.release()


def _commit_event(journal: Path, event: str, issue: dict) -> None:
    target = _issue_file(journal, issue["id"])
    late = _is_late(issue, target)
    previous = (
        target.read_text(encoding="utf-8") if target.exists() else None
    )
    try:
        if not late:
            _write_atomic(target, _normalize(issue))
            run_git(
                journal, "add", "--", str(target.relative_to(journal))
            )
        run_git(
            journal,
            "commit",
            "--allow-empty",
            "--no-verify",
            "-q",
            "-m",
            commit_message(event, issue, late),
        )
    except (GitError, OSError):
        if not late:
            # Verworfenes Ereignis nicht in den nächsten Commit tragen.
            _restore_issue(journal, target, previous)
        raise


def _restore_issue(
    journal: Path, target: Path, previous: str | None
) -> None:
    if previous is None:
        target.unlink(missing_ok=True)
    else:
        _write_atomic(target, previous)
    run_git(
        journal,
        "reset",
        "-q",
        "HEAD",
        "--",
        str(target.relative_to(journal)),
    )


def commit_message(event: str, issue: dict, late: bool) -> str:
    message = (
        f"{event} {issue['id']}: {issue['title']} [{issue['status']}]"
    )
    return f"{message} (verspätet)" if late else message


def _is_late(issue: dict, target: Path) -> bool:
    if not target.is_file():
        return False
    try:
        stored = json.loads(target.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PayloadError("gespeichertes Issue: kein JSON") from exc
    check_issue(stored, ["gespeichertes Issue"])
    return _whole_second(issue["updated_at"]) < _whole_second(
        stored["updated_at"]
    )


def _whole_second(value: str) -> datetime:
    """updated_at ohne Sekundenbruchteile.

    Nur die create-Nutzlast trägt Bruchteile aus dem Speicher; spätere
    Ereignisse liefern die Sekunde aus der DB. Fehlende Bruchteile
    dürfen kein Ereignis verspätet machen; innerhalb derselben Sekunde
    entscheidet die Sperrreihenfolge.
    """
    seconds, _ = timestamp(value)
    return seconds


def _issue_file(journal: Path, issue_id: str) -> Path:
    return journal / ISSUES / f"{issue_id}.json"


def _normalize(issue: dict) -> str:
    return (
        json.dumps(issue, sort_keys=True, indent=2, ensure_ascii=False)
        + "\n"
    )


def _write_atomic(target: Path, text: str) -> None:
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
