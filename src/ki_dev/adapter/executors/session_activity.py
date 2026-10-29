"""Konservative Zeitgrenzen aus Rohzeilen, ohne Dialogvalidierung."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from .session_transcript import is_timestamp, parse_timestamp


@dataclass(frozen=True)
class ActivityBounds:
    earliest: datetime
    latest: datetime


def raw_activity_bounds(
    agent: str, data: bytes
) -> ActivityBounds | None:
    """Alle Rohzeiten begrenzen die Zeiten des normalisierten Dialogs.

    Steuerereignisse können den Bereich erweitern. Deshalb wird nur
    ausgeschlossen, wenn der gesamte Bereich außerhalb liegt. Defekte
    Zeilen oder Zeitfelder liefern keine belastbare Eingrenzung.
    """
    earliest = latest = None
    try:
        for line in data.decode("utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                return None
            for stamp in _timestamps(agent, row):
                if not is_timestamp(stamp):
                    return None
                moment = parse_timestamp(stamp)
                earliest = (
                    moment
                    if earliest is None
                    else min(earliest, moment)
                )
                latest = (
                    moment if latest is None else max(latest, moment)
                )
    except (UnicodeError, json.JSONDecodeError):
        return None
    if earliest is None:
        return None
    return ActivityBounds(earliest, latest)


def _timestamps(agent: str, row: dict) -> list:
    stamps = [row["timestamp"]] if "timestamp" in row else []
    if agent == "codex" and row.get("type") == "session_meta":
        payload = row.get("payload")
        if isinstance(payload, dict) and "timestamp" in payload:
            stamps.append(payload["timestamp"])
    return stamps
