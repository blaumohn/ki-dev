"""Reine Uebergangsentscheidung der begrenzten V0-Maschine.

:func:`advance` ist die einzige oeffentliche Entscheidung. Sie bildet
``(Zustand, Ereignis)`` deterministisch auf einen Folgezustand ab oder
weist den Uebergang mit :class:`InvalidTransition` sichtbar ab. Es gibt
keinen stillen Ruecksprung und keinen stillen Standardfall.

Welches Ereignis in welcher Phase ueberhaupt zulaessig ist, steht als
Tabelle in ``_TRANSITIONS`` am Dateiende. Alles davor sind kleine reine
Funktionen ueber einem :class:`_Step` (Zustand, Ereignis, Grenzen).

Neben der Tabelle gibt es genau eine weitere Zulaessigkeitsbedingung:
``_require_reviewed_result`` verlangt fuer ``CHANGES`` und ``PASS`` ein
tatsaechlich erfasstes und gecheckpointetes Worker-Ergebnis. Der
erstmalige Controller-Aufruf kann daher nur beauftragen, nachfragen
oder eskalieren, aber kein Qualitaetsurteil faellen.

Drei Vertragsregeln sind hier strukturell verankert:

* Ein Lauf kann ohne Worker-Schritt kein Urteil und kein ``PASSED``
  erreichen.
* ``PASS`` fuehrt ausschliesslich nach ``FREEZE_REVIEWED_RESULT``.
* ``PASSED`` ist nur ueber ``FAST_FORWARD_INTEGRATE`` mit positivem
  Integrationsergebnis erreichbar.

Die Begrenztheit ruht allein auf den laufweit monotonen Zaehlern in
``Counters.run_total``: jede ruecklaufende Kante -- ``TASK``,
``CHANGES``, unerklaerter leerer Delta, Prozess- und Protokollfehler --
erhoeht ``worker_attempt``, ``process_retry`` oder
``protocol_attempt``. ``changes_round`` begrenzt zusaetzlich die
Korrekturen innerhalb genau eines TASK und wird von einem neuen TASK
bewusst zurueckgesetzt; der Begrenztheitsnachweis stuetzt sich deshalb
nicht auf ihn.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ki_dev.deltas import StepDeltaAssessment

from .contract import (
    DEFAULT_LIMITS,
    AgentEscalation,
    CheckpointRecorded,
    ControllerChanges,
    ControllerEscalate,
    ControllerNeedsDecision,
    ControllerPass,
    ControllerTask,
    Counters,
    Event,
    FinalizationError,
    FinalResultVerified,
    HistoryFinalized,
    IntegrationCompleted,
    InvalidTransition,
    Limits,
    MachineEscalation,
    MachineEscalationCause,
    MachineState,
    Phase,
    ProtocolError,
    ReviewedResultFrozen,
    RunStarted,
    StepResultCaptured,
    TransitionResult,
    WorkerCompleted,
    WorkerEscalate,
    WorkerInputsPrepared,
    WorkerNeedsDecision,
    WorkerProcessError,
)


@dataclass(frozen=True)
class _Step:
    """Vollstaendige Eingabe genau einer Uebergangsentscheidung."""

    state: MachineState
    event: Event
    limits: Limits


_Handler = Callable[[_Step], TransitionResult]


def advance(
    state: MachineState,
    event: Event,
    limits: Limits = DEFAULT_LIMITS,
) -> TransitionResult:
    """Entscheide den Folgezustand oder weise den Uebergang ab."""
    allowed = _TRANSITIONS.get(state.phase)
    if allowed is None:
        raise InvalidTransition(state, event)
    handler = allowed.get(type(event))
    if handler is None:
        raise InvalidTransition(state, event)
    return handler(_Step(state=state, event=event, limits=limits))


def _goto(
    step: _Step,
    phase: Phase,
    *,
    escalation: AgentEscalation | MachineEscalation | None = None,
    counters: Counters | None = None,
    checkpointed_result: bool | None = None,
) -> TransitionResult:
    return TransitionResult(
        state=step.state.moved_to(
            phase,
            counters=counters,
            checkpointed_result=checkpointed_result,
        ),
        escalation=escalation,
    )


def _pause_by_machine(
    step: _Step,
    cause: MachineEscalationCause,
) -> TransitionResult:
    """Beende den aktiven Zyklus wegen einer Maschinenregel."""
    return _goto(
        step,
        Phase.PAUSED_INTERACTIVE,
        escalation=MachineEscalation(
            cause=cause, resume_point=step.state.phase
        ),
    )


def _pause_by_agent(step: _Step, cause: str) -> TransitionResult:
    """Beende den aktiven Zyklus wegen eines Agentenurteils."""
    return _goto(
        step,
        Phase.PAUSED_INTERACTIVE,
        escalation=AgentEscalation(
            cause=cause, resume_point=step.state.phase
        ),
    )


def _open_worker_cycle(
    step: _Step,
    *,
    as_correction: bool,
) -> TransitionResult:
    """Oeffne einen neuen begrenzten Worker-Zyklus, falls erlaubt.

    Eine Korrektur zehrt am Rundenbudget des laufenden TASK, ein neuer
    TASK setzt es zurueck. Beide verbrauchen ``worker_attempt``, das
    laufweit monoton bleibt und daher auch eine Folge vieler adaptiver
    TASKs begrenzt.
    """
    counters = step.state.counters
    limits = step.limits
    rounds_left = counters.changes_round < limits.changes_rounds
    if as_correction and not rounds_left:
        return _pause_by_machine(
            step, MachineEscalationCause.CHANGES_ROUNDS_EXHAUSTED
        )
    if counters.worker_attempt >= limits.worker_attempts:
        return _pause_by_machine(
            step, MachineEscalationCause.WORKER_ATTEMPTS_EXHAUSTED
        )
    advanced = (
        counters.started_correction()
        if as_correction
        else counters.started_task()
    )
    return _goto(
        step,
        Phase.WORKER_STEP_PREPARE,
        counters=advanced,
        checkpointed_result=False,
    )


def _require_reviewed_result(step: _Step) -> None:
    """Ein Qualitaetsurteil braucht ein gecheckpointetes Ergebnis."""
    if not step.state.checkpointed_result:
        raise InvalidTransition(step.state, step.event)


def _run_started(step: _Step) -> TransitionResult:
    return _goto(step, Phase.CONTROLLER_STEP, checkpointed_result=False)


def _controller_task(step: _Step) -> TransitionResult:
    """``TASK`` beauftragt den naechsten begrenzten Worker-Zyklus."""
    return _open_worker_cycle(step, as_correction=False)


def _controller_changes(step: _Step) -> TransitionResult:
    _require_reviewed_result(step)
    return _open_worker_cycle(step, as_correction=True)


def _controller_needs_decision(step: _Step) -> TransitionResult:
    return _goto(step, Phase.WAITING_DECISION)


def _controller_escalate(step: _Step) -> TransitionResult:
    return _pause_by_agent(step, step.event.cause)


def _controller_pass(step: _Step) -> TransitionResult:
    """``PASS`` friert zunaechst nur das gepruefte Ergebnis ein."""
    _require_reviewed_result(step)
    return _goto(step, Phase.FREEZE_REVIEWED_RESULT)


def _protocol_error(step: _Step) -> TransitionResult:
    """Praezise Rueckkopplung an dieselbe Rolle, aber begrenzt."""
    counters = step.state.counters
    if counters.protocol_attempt >= step.limits.protocol_attempts:
        return _pause_by_machine(
            step, MachineEscalationCause.PROTOCOL_ATTEMPTS_EXHAUSTED
        )
    return _goto(
        step,
        step.state.phase,
        counters=counters.retried_protocol(),
    )


def _worker_inputs_prepared(step: _Step) -> TransitionResult:
    return _goto(step, Phase.WORKER_STEP)


def _worker_completed(step: _Step) -> TransitionResult:
    return _goto(step, Phase.CAPTURE_STEP_RESULT)


def _worker_needs_decision(step: _Step) -> TransitionResult:
    return _goto(step, Phase.WAITING_DECISION)


def _worker_escalate(step: _Step) -> TransitionResult:
    return _pause_by_agent(step, step.event.cause)


def _worker_process_error(step: _Step) -> TransitionResult:
    counters = step.state.counters
    if counters.process_retry >= step.limits.process_retries:
        return _pause_by_machine(
            step, MachineEscalationCause.PROCESS_RETRIES_EXHAUSTED
        )
    return _goto(
        step,
        Phase.WORKER_STEP_PREPARE,
        counters=counters.retried_process(),
    )


def _step_result_captured(step: _Step) -> TransitionResult:
    """Nur ein wirksamer Schrittdelta fuehrt zum Checkpoint."""
    if step.event.assessment is StepDeltaAssessment.EFFECTIVE:
        return _goto(step, Phase.CHECKPOINT)
    return _feed_back_empty_result(step)


def _feed_back_empty_result(step: _Step) -> TransitionResult:
    """Leerer Delta ohne Sonderfall: Rueckkopplung oder Eskalation."""
    counters = step.state.counters
    if counters.changes_round >= step.limits.changes_rounds:
        return _pause_by_machine(
            step, MachineEscalationCause.EMPTY_RESULT_UNRESOLVED
        )
    return _open_worker_cycle(step, as_correction=True)


def _checkpoint_recorded(step: _Step) -> TransitionResult:
    """Erst ab hier liegt ein pruefbares Worker-Ergebnis vor."""
    return _goto(step, Phase.CONTROLLER_STEP, checkpointed_result=True)


def _reviewed_result_frozen(step: _Step) -> TransitionResult:
    return _goto(step, Phase.FINALIZE_HISTORY)


def _history_finalized(step: _Step) -> TransitionResult:
    return _goto(step, Phase.VERIFY_FINAL_RESULT)


def _final_result_verified(step: _Step) -> TransitionResult:
    if not step.event.ok:
        return _pause_by_machine(
            step, MachineEscalationCause.FINAL_VERIFICATION_FAILED
        )
    return _goto(step, Phase.FAST_FORWARD_INTEGRATE)


def _integration_completed(step: _Step) -> TransitionResult:
    """Erst die bewiesene Integration erreicht ``PASSED``."""
    if not step.event.ok:
        return _pause_by_machine(
            step, MachineEscalationCause.INTEGRATION_FAILED
        )
    return _goto(step, Phase.PASSED)


def _finalization_error(step: _Step) -> TransitionResult:
    return _goto(step, Phase.ERROR)


_FINALIZATION_FAULT: dict[type[Event], _Handler] = {
    FinalizationError: _finalization_error,
}

_TRANSITIONS: dict[Phase, dict[type[Event], _Handler]] = {
    Phase.START: {
        RunStarted: _run_started,
    },
    Phase.CONTROLLER_STEP: {
        ControllerTask: _controller_task,
        ControllerChanges: _controller_changes,
        ControllerNeedsDecision: _controller_needs_decision,
        ControllerEscalate: _controller_escalate,
        ControllerPass: _controller_pass,
        ProtocolError: _protocol_error,
    },
    Phase.WORKER_STEP_PREPARE: {
        WorkerInputsPrepared: _worker_inputs_prepared,
    },
    Phase.WORKER_STEP: {
        WorkerCompleted: _worker_completed,
        WorkerNeedsDecision: _worker_needs_decision,
        WorkerEscalate: _worker_escalate,
        WorkerProcessError: _worker_process_error,
        ProtocolError: _protocol_error,
    },
    Phase.CAPTURE_STEP_RESULT: {
        StepResultCaptured: _step_result_captured,
    },
    Phase.CHECKPOINT: {
        CheckpointRecorded: _checkpoint_recorded,
    },
    Phase.FREEZE_REVIEWED_RESULT: {
        ReviewedResultFrozen: _reviewed_result_frozen,
        **_FINALIZATION_FAULT,
    },
    Phase.FINALIZE_HISTORY: {
        HistoryFinalized: _history_finalized,
        **_FINALIZATION_FAULT,
    },
    Phase.VERIFY_FINAL_RESULT: {
        FinalResultVerified: _final_result_verified,
        **_FINALIZATION_FAULT,
    },
    Phase.FAST_FORWARD_INTEGRATE: {
        IntegrationCompleted: _integration_completed,
        **_FINALIZATION_FAULT,
    },
}
