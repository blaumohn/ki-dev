"""Neutrale Datentypen fuer Sitzungstranskripte."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptMessage:
    ordinal: int | float
    role: str
    text: str
    source_line: int


@dataclass(frozen=True)
class SessionTranscript:
    agent: str
    session_id: str
    source_digest: str
    parser_version: str
    messages: tuple[TranscriptMessage, ...]
    diagnostics: Mapping[str, int]


class TranscriptError(ValueError):
    """Sitzung nicht lesbar oder nicht plausibel.

    ``problems`` nennt nur Pruefcode, Zeile, Feldpfad und Zaehler,
    niemals Gespraechsinhalte oder Rohereignisse.
    """

    def __init__(self, problems: tuple[str, ...]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


class TranscriptRequestError(TranscriptError):
    """Anbieter oder Sitzungs-ID ungueltig (vor jedem Dateizugriff)."""

    def __init__(self, problem: str) -> None:
        super().__init__((problem,))
