"""Begrenzte deterministische V0-Zustandsmaschine.

Oeffentliche Nutzung durch den spaeteren Orchestrator:

* :class:`Phase` / :class:`MachineState` -- reiner Laufzustand
* :func:`advance` -- reine Uebergangsentscheidung
* :class:`InvalidTransition` -- sichtbare Abweisung
* :class:`Limits` / :class:`Counters` -- begrenzte aktive Zyklen
* :class:`AgentEscalation` / :class:`MachineEscalation` -- getrennte
  Eskalationsursachen
* :class:`RunState` mit :func:`encode_run_state` /
  :func:`decode_run_state` -- versionierter JSON-Vertrag des
  fortgeschriebenen Laufzustands

Diese Ebene kennt weder Dateien noch Prozesse noch Git-Aktionen.
"""

from __future__ import annotations

from .contract import (
    DEFAULT_LIMITS,
    DELIVERY,
    FINALIZATION_PHASES,
    STOPPED_PHASES,
    TERMINAL_PHASES,
    WAITING_PHASES,
    AgentEscalation,
    CheckpointRecorded,
    ControllerChanges,
    ControllerEscalate,
    ControllerNeedsDecision,
    ControllerPass,
    ControllerTask,
    Counters,
    Escalation,
    Event,
    ExecutionStopped,
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
    ProcessError,
    ProtocolError,
    ResumeRequested,
    ReviewedResultFrozen,
    RunStarted,
    RunState,
    StepResultCaptured,
    TransitionResult,
    WorkerCompleted,
    WorkerEscalate,
    WorkerInputsPrepared,
    WorkerNeedsDecision,
    WorkerProcessError,
)
from .state_json import (
    SCHEMA_VERSION,
    RunStateFormatError,
    decode_run_state,
    encode_run_state,
)
from .transitions import DELIVERY_BOUND, advance, operation

__all__ = [
    "DELIVERY",
    "DEFAULT_LIMITS",
    "FINALIZATION_PHASES",
    "SCHEMA_VERSION",
    "STOPPED_PHASES",
    "TERMINAL_PHASES",
    "WAITING_PHASES",
    "AgentEscalation",
    "CheckpointRecorded",
    "ControllerChanges",
    "ControllerEscalate",
    "ControllerNeedsDecision",
    "ControllerPass",
    "ControllerTask",
    "Counters",
    "Escalation",
    "Event",
    "ExecutionStopped",
    "FinalResultVerified",
    "FinalizationError",
    "HistoryFinalized",
    "IntegrationCompleted",
    "InvalidTransition",
    "Limits",
    "MachineEscalation",
    "MachineEscalationCause",
    "MachineState",
    "Phase",
    "ProcessError",
    "ProtocolError",
    "ResumeRequested",
    "ReviewedResultFrozen",
    "RunStarted",
    "RunState",
    "RunStateFormatError",
    "StepResultCaptured",
    "TransitionResult",
    "WorkerCompleted",
    "WorkerEscalate",
    "WorkerInputsPrepared",
    "WorkerNeedsDecision",
    "WorkerProcessError",
    "DELIVERY_BOUND",
    "advance",
    "operation",
    "decode_run_state",
    "encode_run_state",
]
