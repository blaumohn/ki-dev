"""Warteschlange abarbeiten: Wiederanlauf, Doppelprüfung, Commit, ack.

Der Hook legt sein Ereignis mit enqueue() ab und ruft drain() auf.
drain() arbeitet unter der Journal-Sperre, bis die Queue leer ist; die
Commits folgen also der Eingangsreihenfolge, auch wenn ein später
eingestellter Hook die Sperre zuerst erhält. Ist die Sperre belegt,
bleibt der Eintrag liegen, und der Halter oder der nächste drain
committet ihn.

Ein Kill durch die Hookfrist kann zwischen Commit und ack fallen; der
Wiederanlauf setzt den Eintrag dann zurück, und die Doppelprüfung
findet seinen Trailer im Log. Ein Kill während git schreibt hinterlässt
.git/index.lock; unter der Sperre ist sie verwaist (nur dieses Werkzeug
schreibt das Journal) und wird entfernt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ki_dev.beads_journal import queue
from ki_dev.beads_journal.contract import PayloadError
from ki_dev.beads_journal.git import GitError, run_git
from ki_dev.beads_journal.journal import (
    TRAILER,
    JournalError,
    commit_event,
    io_error,
    locked,
    log_error,
)

RECOVERY_EVENT = "wiederanlauf"


class DrainStopped(JournalError):
    """Vorübergehender Fehler; Eintrag bleibt, Grund steht im Log."""


@dataclass(frozen=True)
class DrainResult:
    committed: int
    failed: int


def enqueue(journal: Path, event: str, issue: dict) -> int:
    with queue.opened(journal) as handle:
        return queue.put(handle, event, issue)


def record_invalid(
    journal: Path, event: str, issue_id: str, reason: str
) -> None:
    """Ungültige Nutzlast als fehlgeschlagen vermerken, protokollieren.

    Der Grund landet auch dann im Log, wenn die Queue scheitert.
    """
    queue_id = None
    try:
        with queue.opened(journal) as handle:
            queue_id = queue.put_failed(handle, event, issue_id, reason)
    finally:
        log_error(journal, event, issue_id, reason, queue_id)


def drain(journal: Path) -> DrainResult:
    """Committet alle bereiten Einträge; zählt Commits und Fehlschläge.

    LockBusy: Sperre belegt, nichts geändert. DrainStopped: ein Eintrag
    scheiterte vorübergehend und bleibt für den nächsten drain.
    """
    with locked(journal), queue.opened(journal) as handle:
        _recover(journal, handle)
        committed = committed_event_ids(journal)
        outcomes = []
        while (entry := queue.claim_next(handle)) is not None:
            if str(entry.queue_id) in committed:
                queue.ack(handle, entry.queue_id)
                continue
            outcomes.append(_process(journal, handle, entry))
        queue.prune_acked(handle)
    return DrainResult(sum(outcomes), outcomes.count(False))


def committed_event_ids(journal: Path) -> set[str]:
    """Queue-IDs aus den Trailern; exakter Zeilenvergleich, kein --grep.

    --grep="1" träfe auch "10".
    """
    _, stdout = run_git(
        journal,
        "log",
        f"--format=%(trailers:key={TRAILER},valueonly)",
    )
    return {
        line.strip() for line in stdout.splitlines() if line.strip()
    }


def _recover(journal: Path, handle) -> None:
    queue.resume_unacked(handle)
    index_lock = journal / ".git" / "index.lock"
    if index_lock.exists():
        index_lock.unlink()
        log_error(
            journal,
            RECOVERY_EVENT,
            "-",
            "verwaiste .git/index.lock entfernt",
        )


def _process(journal: Path, handle, entry: queue.Entry) -> bool:
    """Committet einen Eintrag; False bei dauerhaftem Fehler."""
    if entry.issue is None:
        # Als ungültig eingestellt; put_failed kam nicht zum Markieren.
        queue.ack_failed(handle, entry, entry.record["reason"])
        return False
    try:
        commit_event(journal, entry.event, entry.issue, entry.queue_id)
    except PayloadError as exc:
        # Etwa eine kaputte gespeicherte Issue-Datei: ein erneuter
        # Versuch scheitert gleich; die Queue darf nicht stehen bleiben.
        queue.ack_failed(handle, entry, str(exc))
        _log_entry(journal, entry, str(exc))
        return False
    except (GitError, OSError) as exc:
        queue.release(handle, entry.queue_id)
        error = io_error(exc) if isinstance(exc, OSError) else exc
        reason = f"{error}; bleibt in der Warteschlange"
        _log_entry(journal, entry, reason)
        raise DrainStopped(f"#{entry.queue_id}: {reason}") from exc
    queue.ack(handle, entry.queue_id)
    return True


def _log_entry(journal: Path, entry: queue.Entry, reason: str) -> None:
    log_error(
        journal, entry.event, entry.issue_id, reason, entry.queue_id
    )
