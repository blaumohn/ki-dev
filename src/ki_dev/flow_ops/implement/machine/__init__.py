"""Begrenzte deterministische Ablauf-Maschine (implement.toml).

Oeffentliche Nutzung durch den spaeteren Orchestrator:

* :class:`Phase` / :class:`MachineState` -- reiner Laufzustand
* :func:`advance` -- reine Uebergangsentscheidung ueber
  python-statemachine (:class:`ImplementModel` sind die Ops)
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
    IMPLEMENT,
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
    DecisionTaken,
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
from .model import (
    EVENT_TYPES,
    IMPLEMENT_CHART,
    OPERATION_GUARDS,
    ImplementModel,
    advance,
    operation,
    operation_of,
    phase_of,
    step,
)
from .state_json import (
    SCHEMA_VERSION,
    RunStateFormatError,
    decode_run_state,
    encode_run_state,
)

__all__ = [
    "IMPLEMENT",
    "DEFAULT_LIMITS",
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
    "DecisionTaken",
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
    "EVENT_TYPES",
    "IMPLEMENT_CHART",
    "OPERATION_GUARDS",
    "ImplementModel",
    "advance",
    "operation",
    "operation_of",
    "phase_of",
    "step",
    "decode_run_state",
    "encode_run_state",
]
