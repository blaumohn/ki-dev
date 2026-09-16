"""Executor-unabhaengiger Vertrag fuer genau einen Agenten-Turn.

Die Kontrollschleife kennt nur die Typen dieses Moduls. Sie kennt
weder Claude- noch Codex-spezifische Argumente. Ein Turn ist genau
ein synchroner Prozessaufruf; sein Ende ist die Schrittgrenze.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class Effort(StrEnum):
    """Angeforderter Denkaufwand fuer einen Turn."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TurnStatus(StrEnum):
    """Eindeutiger Ausgang eines Turn-Prozesses.

    Die vier Werte sind bewusst disjunkt, damit Fehler- und
    Timeoutfaelle nie zusammenfallen und nie stillschweigend als
    Erfolg gelten.
    """

    OK = "ok"
    NONZERO_EXIT = "nonzero_exit"
    TIMEOUT = "timeout"
    START_ERROR = "start_error"


@dataclass(frozen=True)
class TurnRequest:
    """Eingabe fuer einen einzelnen synchronen Turn."""

    session_id: str
    message: str
    model: str
    effort: Effort

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("session_id darf nicht leer sein")
        if not self.message:
            raise ValueError("message darf nicht leer sein")
        if not self.model:
            raise ValueError("model darf nicht leer sein")
        if not isinstance(self.effort, Effort):
            raise TypeError("effort muss ein Effort-Wert sein")


@dataclass(frozen=True)
class TurnResult:
    """Einheitliches Ergebnis eines Turn-Prozesses.

    ``stdout``, ``stderr``, ``exit_code`` und ``argv`` werden fuer
    jeden Ausgang gleich befuellt, soweit verfuegbar. ``error``
    traegt bei jedem Nicht-Erfolg eine erklaerende Meldung.
    """

    status: TurnStatus
    exit_code: int | None
    stdout: str
    stderr: str
    argv: tuple[str, ...]
    duration_s: float
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status is TurnStatus.OK


@runtime_checkable
class Executor(Protocol):
    """Oeffentlicher Turn-Vertrag, den beide Adapter erfuellen."""

    name: str

    def send_turn(self, request: TurnRequest) -> TurnResult: ...
