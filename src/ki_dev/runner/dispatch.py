"""Übergaben an Executoren: wer eine Übergabe bearbeitet.

Die Rolle steht am Zustand des Ablaufs (``role`` der Übergabe), welcher
Executor sie bearbeitet, sagt das Profil (Rolle → Executor; eine
Übergabe ohne Rolle, etwa eine Entscheidung des Menschen, unter
``None``). Den Text der Übergabe und die Deutung der Antwort steckt
der Aufrufer ein; der Ausführer kennt weder Rollen- noch Phasennamen.
Fehlt die Antwort noch (Bote), hält der Lauf
(:class:`~ki_dev.runner.protocol.AwaitingAnswer`).
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
from ki_dev.run_store import RunStoreError
from ki_dev.runner.package import Handoff
from ki_dev.runner.protocol import AwaitingAnswer

Render = Callable[[Handoff], str]
"""Text der Übergabe (Vorlage und Bausteine)."""

Read = Callable[[Handoff, str], tuple[dict, str]]
"""Formale Antwort → neue Laufdaten und Ereignis des Ablaufs; ein
Vertragsfehler ist eine Ausnahme des Aufrufers."""


@dataclass(frozen=True)
class Dispatch:
    """Bearbeitet eine Übergabe mit dem Executor ihrer Rolle
    (:data:`~ki_dev.runner.package.TurnRun`)."""

    flow: Flow
    executors: Mapping[str | None, TurnExecutor]
    render: Render
    read: Read
    workdir: Path
    env: Mapping[str, str] = field(default_factory=dict)

    def __call__(self, handoff: Handoff) -> dict[str, object]:
        role = role_of(self.flow, handoff.state)
        executor = self.executors.get(role)
        if executor is None:
            raise RunStoreError(
                f"{handoff.state}: kein Executor für die Rolle {role}"
            )
        prompt = self.render(handoff)
        request = TurnPrompt(
            handoff.attempt, prompt, self.workdir, self.env
        )
        try:
            answer = executor.ask(request)
        except AnswerPending as exc:
            raise AwaitingAnswer(str(exc)) from exc
        update, event = self.read(handoff, answer)
        return {"event": event, "update": update}


def role_of(flow: Flow, state: str) -> str | None:
    """Rolle der Übergabe in ``state`` (``None``: keine Rolle, etwa
    eine Entscheidung des Menschen)."""
    for operation in flow.state(state).operations:
        if operation.turn is not None:
            return operation.role
    return None
