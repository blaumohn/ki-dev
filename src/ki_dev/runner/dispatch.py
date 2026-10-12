"""Übergaben an Executoren: wer eine Übergabe bearbeitet.

Die Rolle steht am Zustand des Ablaufs (``role`` der Übergabe), welcher
Executor sie bearbeitet, sagt das Profil (Rolle → Executor). Ohne
Executor für die Rolle hält der Lauf (``ki-dev step``: der Mensch ist
Bote). Den Text der Übergabe und die Deutung der Antwort steckt der
Aufrufer ein; der Ausführer kennt weder Rollen- noch Phasennamen.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from ki_dev.adapter.contract import (
    AnswerPending,
    TurnExecutor,
    TurnPrompt,
)
from ki_dev.flow.model import Flow
from ki_dev.runner.planning import Halt, PlanningContext

Render = Callable[[Halt], str]
"""Text der Übergabe dieses Halts (Vorlage und Bausteine)."""

Read = Callable[[Halt, str], tuple[str, PlanningContext]]
"""Formale Antwort → Ereignis des Ablaufs und Laufdaten; ein
Vertragsfehler ist eine Ausnahme des Aufrufers."""


@dataclass(frozen=True)
class Dispatch:
    """Bearbeitet die Übergabe eines Halts mit dem Executor seiner
    Rolle (:data:`~ki_dev.runner.planning.TurnCall`)."""

    flow: Flow
    executors: Mapping[str, TurnExecutor]
    render: Render
    read: Read
    workdir: Path
    env: Mapping[str, str] = field(default_factory=dict)

    def __call__(
        self, halt: Halt
    ) -> tuple[str, PlanningContext] | None:
        role = role_of(self.flow, halt.state)
        executor = None if role is None else self.executors.get(role)
        if executor is None or halt.attempt is None:
            return None
        request = TurnPrompt(
            halt.attempt, self.render(halt), self.workdir, self.env
        )
        try:
            answer = executor.ask(request)
        except AnswerPending:
            return None
        return self.read(halt, answer)


def role_of(flow: Flow, state: str) -> str | None:
    """Rolle der Übergabe in ``state`` (``None``: keine Rolle, etwa
    eine Entscheidung des Menschen)."""
    for operation in flow.state(state).operations:
        if operation.turn is not None:
            return operation.role
    return None
