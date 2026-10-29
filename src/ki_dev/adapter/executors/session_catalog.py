"""Sitzungen der Anbieter auflisten und automatische Vorspänne filtern.

Ein-/Ausgabegrenze wie die Transkriptleser: Umgebung, Home und
Sitzungsordner werden nur hier gelesen. Die Reihenfolge folgt der
Aenderungszeit der Sitzungsdatei; sie waehlt nur aus, welche
Sitzungen gelesen werden. Die Aktivitaetszeit stammt weiterhin aus
dem Transkript.
"""

from __future__ import annotations

import os
from collections import Counter
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
from .session_config import session_environ
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
    path: Path
    ambiguous: bool = False


@dataclass(frozen=True)
class SessionListing:
    """Neueste Sitzungen; ``missing`` nennt Anbieter ohne Ordner."""

    refs: tuple[SessionRef, ...]
    missing: tuple[str, ...]


def recent_sessions(
    agents: Sequence[str],
    limit: int | None,
    *,
    exclude: Callable[[str, Path], bool] | None = None,
    config: Mapping | None = None,
) -> SessionListing:
    """Hoechstens ``limit`` Sitzungen der Anbieter, neueste zuerst.

    Bei Gleichstand entscheiden Anbieter und ID. Ein fehlender
    Sitzungsordner ist kein Fehler dieser Funktion: der Anbieter
    erscheint in ``missing``, der Aufrufer entscheidet.
    """
    if limit is not None and limit < 1:
        raise ValueError("limit muss positiv sein")
    try:
        environ = session_environ(os.environ, config)
    except ValueError as exc:
        raise TranscriptError((str(exc),)) from None
    refs: list[SessionRef] = []
    missing: list[str] = []
    for agent in agents:
        root = _root(agent, environ)
        if not root.is_dir():
            missing.append(agent)
            continue
        refs.extend(_refs(agent, root))
    refs.sort(key=lambda r: (-r.modified, r.agent, r.session_id))
    selected: list[SessionRef] = []
    for ref in refs:
        if exclude is not None and exclude(ref.agent, ref.path):
            continue
        selected.append(ref)
        if limit is not None and len(selected) == limit:
            break
    return SessionListing(tuple(selected), tuple(missing))


def _root(agent: str, environ: Mapping[str, str]) -> Path:
    try:
        return _RESOLVERS[agent](environ, Path.home())
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
        sources = _LISTERS[agent](root)
        counts = Counter(session_id for session_id, _ in sources)
        return [
            SessionRef(
                agent,
                session_id,
                path.stat().st_mtime,
                path,
                counts[session_id] > 1,
            )
            for session_id, path in sources
        ]
    except OSError as exc:
        raise TranscriptError(
            (f"Sitzungen {agent} nicht lesbar ({type(exc).__name__})",)
        ) from None
