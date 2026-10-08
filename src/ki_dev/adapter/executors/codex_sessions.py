"""Codex-Sitzungsablage: Verzeichniskonfiguration und Dateisuche.

Gemeinsam genutzt von ``metering.codex_quota`` (kontoweite Quota-Suche)
und dem Transkriptadapter. Dieses Modul importiert nichts aus
``metering``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

SESSIONS_DIR_ENV = "KI_DEV_CODEX_SESSIONS_DIR"
CODEX_HOME_ENV = "CODEX_HOME"

# Codex-Sitzungs-IDs sind UUIDs; die Positivliste schliesst
# Pfadseparatoren, ``..`` und Glob-Metazeichen sicher aus.
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")


def validate_codex_session_id(session_id: str) -> None:
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("ungueltige Codex-session_id")


def resolve_codex_sessions_dir(
    environ: Mapping[str, str], home: Path
) -> Path:
    """Ordner der Sitzungen: ausdruecklicher Ordner, sonst
    ``CODEX_HOME/sessions``, sonst ``~/.codex/sessions``.

    Ein gesetzter, aber leerer Wert ist ein Fehler, kein Fallback.
    """
    for name in (SESSIONS_DIR_ENV, CODEX_HOME_ENV):
        if name in environ:
            value = environ[name]
            if not value.strip():
                raise ValueError(f"{name} ist gesetzt, aber leer")
            base = Path(value)
            return (
                base if name == SESSIONS_DIR_ENV else base / "sessions"
            )
    return home / ".codex" / "sessions"


def find_session_rollouts(root: Path, session_id: str) -> list[Path]:
    validate_codex_session_id(session_id)
    return sorted(root.glob(f"*/*/*/rollout-*-{session_id}.jsonl"))


def find_session_rollout(root: Path, session_id: str) -> Path:
    """Genau eine Rollout-Datei der Sitzung, sonst ``ValueError``."""
    found = find_session_rollouts(root, session_id)
    if len(found) != 1:
        raise ValueError("Codex-Rollout fehlt oder ist mehrdeutig")
    return found[0]
