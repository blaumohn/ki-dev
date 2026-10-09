"""Claude-Sitzungsablage: Verzeichniskonfiguration und Dateisuche.

Gemeinsam genutzt von ``metering.claude_context_tokens`` und dem
Transkriptadapter. Dieses Modul importiert nichts aus ``metering``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

SESSIONS_DIR_ENV = "KI_DEV_CLAUDE_SESSIONS_DIR"

# Claude-Sitzungs-IDs sind UUIDs; die Positivliste schliesst
# Pfadseparatoren, ``..`` und Glob-Metazeichen sicher aus.
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


def validate_claude_session_id(session_id: str) -> None:
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("ungueltige Claude-session_id")


def resolve_claude_sessions_dir(
    environ: Mapping[str, str], home: Path
) -> Path:
    """Projektwurzel der Sitzungen: ausdruecklicher Ordner, sonst
    ``~/.claude/projects``.

    Ein gesetzter, aber leerer Wert ist ein Fehler, kein Fallback.
    """
    if SESSIONS_DIR_ENV in environ:
        value = environ[SESSIONS_DIR_ENV]
        if not value.strip():
            raise ValueError(
                f"{SESSIONS_DIR_ENV} ist gesetzt, aber leer"
            )
        return Path(value)
    return home / ".claude" / "projects"


def find_claude_sessions(root: Path, session_id: str) -> list[Path]:
    """Sitzungsdateien ``<projekt>/<session_id>.jsonl`` in ``root``."""
    validate_claude_session_id(session_id)
    return sorted(root.glob(f"*/{session_id}.jsonl"))


def list_claude_sessions(root: Path) -> list[tuple[str, Path]]:
    """Alle Hauptsitzungen ``<projekt>/<session_id>.jsonl`` als
    ``(session_id, Pfad)``.

    Unterordner (Subagenten) liegen tiefer und zaehlen nicht mit;
    Dateien ohne gueltigen ID-Namen sind keine Sitzungen.
    """
    return [
        (path.stem, path)
        for path in sorted(root.glob("*/*.jsonl"))
        if _SESSION_ID.fullmatch(path.stem)
    ]
