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

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from ki_dev.adapter.contract import (
    AnswerPending,
    TurnExecutor,
    TurnPrompt,
)
from ki_dev.adapter.executors.contract import Measure
from ki_dev.flow.model import Flow
from ki_dev.run_store import RunStoreError
from ki_dev.runner.meter import Meter
from ki_dev.runner.package import Handoff
from ki_dev.runner.protocol import AwaitingAnswer, TurnFailed
from ki_dev.runner.safety import CallLedger
from ki_dev.usage import UsageStatus
from ki_dev.usage_accounting import UsageAttribution, UsagePurpose

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
    meter: Meter | None = None
    ledger: CallLedger | None = None
    """Budgetbilanz der Aufrufe (Wirkung): bucht, was ein Executor mit
    ``Measure.BUDGET`` ausführt."""

    def measure(self, handoff: Handoff) -> dict | None:
        """Messung vor dem Start der Übergabe (Wirkung, keine
        Entscheidung); ``None``: nichts zu messen."""
        if self.meter is None:
            return None
        return self.meter.measure(role_of(self.flow, handoff.state))

    def reserve(self, handoff: Handoff) -> str | None:
        """Reservierung der Kennung vor ``start`` (Wirkung, nur
        schreiben); ``None``, wenn der Executor nicht im Budget
        gebucht wird. Erlaubt ist der Aufruf erst, wenn der Wächter
        ``within_limits`` der Lauf-Maschine das sagt."""
        executor = self._executor(handoff)
        if Measure.BUDGET not in executor.spec.measures:
            return None
        if self.ledger is None:
            raise RunStoreError(
                f"{handoff.state}: Budget ohne Verbrauchsbilanz"
            )
        call_id = f"{handoff.operation}-{uuid.uuid4().hex}"
        self.ledger.reserve(
            call_id,
            str(handoff.operation),
            True,
            executor.spec.transport,
            attribution=self._attribution(handoff, executor),
        )
        return call_id

    def reconcile(self, call_id: str, artifact: object) -> None:
        """Abgleich eines unklaren Aufrufs mit dem Nachweis des
        Menschen."""
        if self.ledger is None:
            raise RunStoreError("Abgleich ohne Verbrauchsbilanz")
        self.ledger.reconcile(call_id, artifact)

    def __call__(self, handoff: Handoff) -> dict[str, object]:
        executor = self._executor(handoff)
        prompt = self.render(handoff)
        request = TurnPrompt(
            handoff.attempt, prompt, self.workdir, self.env
        )
        try:
            answer = executor.ask(request)
        except AnswerPending as exc:
            self._book(handoff, executor, f"Antwort ausstehend: {exc}")
            raise AwaitingAnswer(str(exc)) from exc
        except Exception as exc:
            if handoff.call_id is None:
                raise
            reason = f"{type(exc).__name__}: {exc}"
            self._book(handoff, executor, reason)
            raise TurnFailed(reason) from exc
        self._book(handoff, executor, None)
        update, event = self.read(handoff, answer)
        return {
            "event": event,
            "update": update,
            "adapter": executor.spec.name,
        }

    def _executor(self, handoff: Handoff) -> TurnExecutor:
        role = role_of(self.flow, handoff.state)
        executor = self.executors.get(role)
        if executor is None:
            raise RunStoreError(
                f"{handoff.state}: kein Executor für die Rolle {role}"
            )
        return executor

    def _book(
        self,
        handoff: Handoff,
        executor: TurnExecutor,
        error: str | None,
    ) -> None:
        """Verbrauch zuerst buchen, dann die Reservierung abschließen;
        sonst bliebe sie auch nach einem Fehler ungeklärt."""
        if self.ledger is None or handoff.call_id is None:
            return
        result = getattr(executor, "last_result", None)
        event = result.usage_event if result is not None else None
        if event is not None and event.status in (
            UsageStatus.MEASURED,
            UsageStatus.PARTIAL,
        ):
            self.ledger.record_usage(
                handoff.call_id,
                event,
                f"turn:{handoff.call_id}",
                summary=True,
            )
        self.ledger.finish(handoff.call_id, result, error)

    def _attribution(
        self, handoff: Handoff, executor: TurnExecutor
    ) -> UsageAttribution:
        """Zurechnung zum Auftrag aus ``usage_task`` der Laufdaten."""
        role = role_of(self.flow, handoff.state) or handoff.state
        binding = handoff.data.get("usage_task")
        if not isinstance(binding, Mapping):
            binding = {}
        if role == "review":
            purpose = UsagePurpose.REVIEW
        elif self.flow.state(handoff.state).kind == "correction":
            purpose = UsagePurpose.REPAIR
        else:
            purpose = UsagePurpose.IMPLEMENTATION
        return UsageAttribution(
            bead_id=binding.get("bead_id"),
            task_revision=binding.get("task_revision"),
            family_id=binding.get("family_id"),
            family_revision=binding.get("family_revision"),
            parent_bead_id=binding.get("parent_bead_id"),
            role=role,
            purpose=purpose,
            session_id=getattr(executor, "session_id", None),
        )


def role_of(flow: Flow, state: str) -> str | None:
    """Rolle der Übergabe in ``state`` (``None``: keine Rolle, etwa
    eine Entscheidung des Menschen)."""
    for operation in flow.state(state).operations:
        if operation.turn is not None:
            return operation.role
    return None
