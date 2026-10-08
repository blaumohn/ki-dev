"""Gemeinsamer Ereignisvorrat und enge Grenzen fuer die Maschinentests.

``EVENT_POOL`` enthaelt genau eine repraesentative Auspraegung jedes
Ereignistyps sowie beide Auspraegungen der Ereignisse mit Ergebnisfeld.
``TIGHT_LIMITS`` haelt den erreichbaren Zustandsraum klein genug, um ihn
vollstaendig aufzuzaehlen.
"""

from __future__ import annotations

from ki_dev.deltas import StepDeltaAssessment
from ki_dev.runner.machine import (
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
    ResumeRequested(Phase.WORKER_STEP),
)
