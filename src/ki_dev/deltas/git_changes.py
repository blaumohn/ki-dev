"""Git-Referenzgrenzen und Git-Deltas ueber die Git-Historie.

``ki-dev`` baut keine eigene Git-Snapshot- oder Vergleichslogik: die
Basis- und Ergebnisreferenz sind Commit-Hashes, der Delta ist die
Ausgabe von ``git diff``. Der Schrittcheckpoint haengt genau einen
Commit an; die laufende Pruefgeschichte wird nie umgeschrieben
(Anlage B, Planerausgabe 35).
"""

from __future__ import annotations

from pathlib import Path

from .command import run_command
from .contract import (
    ChangeMedium,
    GitDelta,
    GitFileChange,
    RefBoundary,
    VcsRef,
)


def capture_git_ref(repo: Path) -> VcsRef:
    """Erfasse den aktuellen ``HEAD``-Commit reproduzierbar."""
    out = _git(repo, "rev-parse", "HEAD")
    return VcsRef(ChangeMedium.GIT, out.strip())


def checkpoint_git_step(repo: Path, *, message: str) -> VcsRef:
    """Haenge den Schrittstand als genau einen Commit an.

    Ohne Arbeitsbaumaenderung entsteht kein Commit; der zurueckgegebene
    ``HEAD`` ist dann unveraendert und der Schrittdelta bleibt leer.
    Warum ein Schritt ohne Aenderung endete, entscheidet die
    No-op-/Ergebnispruefung, nicht dieser Aufruf.
    """
    if not message.strip():
        raise ValueError("checkpoint-Nachricht darf nicht leer sein")
    _git(repo, "add", "-A")
    if _has_staged_changes(repo):
        _git(repo, "commit", "--message", message)
    return capture_git_ref(repo)


def build_git_delta(repo: Path, boundary: RefBoundary) -> GitDelta:
    """Bilde den Git-Delta zwischen Basis- und Ergebnisreferenz."""
    if boundary.medium is not ChangeMedium.GIT:
        raise ValueError("RefBoundary ist nicht git")
    span = f"{boundary.base.value}..{boundary.result.value}"
    files = _name_status(repo, span)
    patch = _git(repo, "diff", span)
    return GitDelta(boundary=boundary, files=files, patch=patch)


def _name_status(repo: Path, span: str) -> tuple[GitFileChange, ...]:
    raw = _git(repo, "diff", "--name-status", span)
    changes = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        status, _, rest = line.partition("\t")
        path = rest.replace("\t", " -> ")
        changes.append(GitFileChange(status=status.strip(), path=path))
    return tuple(changes)


def _has_staged_changes(repo: Path) -> bool:
    staged = _git(repo, "diff", "--cached", "--name-only")
    return bool(staged.strip())


def _git(repo: Path, *args: str) -> str:
    argv = ["git", "-C", str(repo), *args]
    return run_command(argv).require_success()
