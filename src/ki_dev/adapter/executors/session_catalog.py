"""Neueste Sitzungen der Anbieter auflisten (nur Dateien, kein Inhalt).

Ein-/Ausgabegrenze wie die Transkriptleser: Umgebung, Home und
Sitzungsordner werden nur hier gelesen. Die Reihenfolge folgt der
Aenderungszeit der Sitzungsdatei; sie waehlt nur aus, welche
Sitzungen gelesen werden. Die Aktivitaetszeit stammt weiterhin aus
dem Transkript.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .claude_sessions import (
    list_claude_sessions,
    resolve_claude_sessions_dir,
)
from .codex_sessions import (
    list_session_rollouts,
    resolve_codex_sessions_dir,
)
from .session_transcript import TranscriptError

_RESOLVERS: dict[str, Callable[[Mapping[str, str], Path], Path]] = {
    "codex": resolve_codex_sessions_dir,
    "claude": resolve_claude_sessions_dir,
}
_LISTERS: dict[str, Callable[[Path], list[tuple[str, Path]]]] = {
    "codex": list_session_rollouts,
    "claude": list_claude_sessions,
}


@dataclass(frozen=True)
class SessionRef:
    agent: str
    session_id: str
    modified: float


@dataclass(frozen=True)
class SessionListing:
    """Neueste Sitzungen; ``missing`` nennt Anbieter ohne Ordner."""

    refs: tuple[SessionRef, ...]
    missing: tuple[str, ...]


def recent_sessions(
    agents: Sequence[str], limit: int
) -> SessionListing:
    """Hoechstens ``limit`` Sitzungen der Anbieter, neueste zuerst.

    Bei Gleichstand entscheiden Anbieter und ID. Ein fehlender
    Sitzungsordner ist kein Fehler dieser Funktion: der Anbieter
    erscheint in ``missing``, der Aufrufer entscheidet.
    """
    if limit < 1:
        raise ValueError("limit muss positiv sein")
    refs: list[SessionRef] = []
    missing: list[str] = []
    for agent in agents:
        root = _root(agent)
        if not root.is_dir():
            missing.append(agent)
            continue
        refs.extend(_refs(agent, root))
    refs.sort(key=lambda r: (-r.modified, r.agent, r.session_id))
    return SessionListing(tuple(refs[:limit]), tuple(missing))


def _root(agent: str) -> Path:
    try:
        return _RESOLVERS[agent](os.environ, Path.home())
    except ValueError as exc:
        raise TranscriptError(
            (f"Sitzungsordner {agent} nicht bestimmbar: {exc}",)
        ) from None
    except RuntimeError:
        raise TranscriptError(
            (
                f"Sitzungsordner {agent} nicht bestimmbar: "
                "Home-Verzeichnis unbekannt",
            )
        ) from None


def _refs(agent: str, root: Path) -> list[SessionRef]:
    try:
        return [
            SessionRef(agent, session_id, path.stat().st_mtime)
            for session_id, path in _LISTERS[agent](root)
        ]
    except OSError as exc:
        raise TranscriptError(
            (f"Sitzungen {agent} nicht lesbar ({type(exc).__name__})",)
        ) from None
