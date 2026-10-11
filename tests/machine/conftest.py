"""Gemeinsamer Ereignisvorrat und enge Grenzen fuer die Maschinentests.

``EVENT_POOL`` enthaelt genau eine repraesentative Auspraegung jedes
Ereignistyps sowie beide Auspraegungen der Ereignisse mit Ergebnisfeld.
``TIGHT_LIMITS`` haelt den erreichbaren Zustandsraum klein genug, um ihn
vollstaendig aufzuzaehlen. ``TRANSITIONS`` ist die Sicht des Ablaufs:
welche Ereignistypen je Zustand ueberhaupt eine Kante haben.
"""

from __future__ import annotations

from ki_dev.deltas import StepDeltaAssessment
from ki_dev.runner.machine import (
    EVENT_TYPES,
    IMPLEMENT,
    CheckpointRecorded,
    ControllerChanges,
    ControllerEscalate,
    ControllerNeedsDecision,
    ControllerPass,
    ControllerTask,
    Event,
    ExecutionStopped,
    FinalizationError,
    FinalResultVerified,
    HistoryFinalized,
    IntegrationCompleted,
    Limits,
    Phase,
    ProcessError,
    ProtocolError,
    ResumeRequested,
    ReviewedResultFrozen,
    RunStarted,
    StepResultCaptured,
    WorkerCompleted,
    WorkerEscalate,
    WorkerInputsPrepared,
    WorkerNeedsDecision,
    WorkerProcessError,
)

TIGHT_LIMITS = Limits(
    protocol_attempts=2,
    worker_attempts=3,
    changes_rounds=2,
    process_retries=2,
)

EVENT_POOL: tuple[Event, ...] = (
    RunStarted(),
    ControllerTask("Implementiere X"),
    ControllerChanges("Test fuer Y fehlt"),
    ControllerNeedsDecision("Welche Ablage?"),
    ControllerEscalate("Werkzeugverhalten unklar"),
    ControllerPass(),
    WorkerInputsPrepared(),
    WorkerCompleted(),
    WorkerNeedsDecision("Welches Schema?"),
    WorkerEscalate("Zustand praktisch unklar"),
    WorkerProcessError("exit 137"),
    StepResultCaptured(StepDeltaAssessment.EFFECTIVE),
    StepResultCaptured(StepDeltaAssessment.EMPTY_UNEXPLAINED),
    CheckpointRecorded(),
    ProtocolError("kein Ergebnis-Trailer"),
    ReviewedResultFrozen(),
    HistoryFinalized(),
    FinalResultVerified(ok=True),
    FinalResultVerified(ok=False),
    IntegrationCompleted(ok=True),
    IntegrationCompleted(ok=False),
    FinalizationError("Referenz fehlt"),
    ProcessError("bd nicht erreichbar"),
    ExecutionStopped("Kontextgrenze erreicht"),
    ResumeRequested(),
)

TRANSITIONS: dict[Phase, dict[type[Event], tuple[str, ...]]] = {}
for _t in IMPLEMENT.transitions:
    _row = TRANSITIONS.setdefault(Phase(_t.source), {})
    _type = EVENT_TYPES[_t.event]
    _row[_type] = (*_row.get(_type, ()), _t.target)
