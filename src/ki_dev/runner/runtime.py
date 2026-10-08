"""LangGraph-Laufzeit des Ausführers: fährt delivery.toml bis zum
Halt."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import NotRequired, Protocol, TypedDict, cast

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ki_dev.adapter import manual, mock
from ki_dev.adapter.agent import (
    AgentReviewer,
    AgentWorker,
)
from ki_dev.adapter.contract import (
    AgentTurnError,
    Reviewer,
    ReviewRequest,
    RunTask,
    Worker,
    WorkReport,
    WorkRequest,
)
from ki_dev.adapter.executors.contract import ContextStatus, QuotaStatus
from ki_dev.adapter.manual import ManualInputPending, ManualRelay
from ki_dev.deltas import (
    ControllerContext,
    StepDeltaAssessment,
    assess_step_delta,
)
from ki_dev.flow.model import (
    WAIT_KIND,
    FlowError,
    Transition,
    Verdict,
    targets,
)
from ki_dev.repository_finalization import Finalizer
from ki_dev.review_context import (
    DEFAULT_PROJECTION_LIMITS,
    ProjectionLimits,
    project_review_context,
)
from ki_dev.run_store import RunStore, RunStoreError
from ki_dev.runner.events import event_record
from ki_dev.runner.machine import (
    DELIVERY,
    DELIVERY_BOUND,
    FINALIZATION_PHASES,
    WAITING_PHASES,
    AgentEscalation,
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
    WorkerInputsPrepared,
    WorkerProcessError,
    advance,
    decode_run_state,
    encode_run_state,
    operation,
)
from ki_dev.runner.review_output import (
    REVIEW_VOCABULARY,
    AgentProtocolError,
    ReviewDecision,
    bind_review_decision,
    parse_review_decision,
)
from ki_dev.runner.safety import (
    CallLedger,
    QuotaBaseline,
    SafetyLimits,
    SafetyStop,
    stagnation_reason,
)
from ki_dev.runner.session_handoff import build_handoff
from ki_dev.usage import UsageStatus
from ki_dev.usage_accounting import UsageAttribution, UsagePurpose

# Operationen aus ``delivery.toml``: sofort erzeugte Ereignisse
# (``_tick``) und persistierte externe Wirkungen
# (``_execute_operation``). Beide Mengen zusammen müssen genau das
# Vokabular des Ablaufs sein.
_IMMEDIATE_OPERATIONS = frozenset(
    {"start", "task", "prepare", "checkpoint"}
)
_EXTERNAL_OPERATIONS = frozenset(
    {
        "work",
        "review",
        "evidence",
        "freeze",
        "finalize_history",
        "verify_final",
        "integrate",
    }
)
if set(
    DELIVERY_BOUND.flow.vocabulary.operations
) != _IMMEDIATE_OPERATIONS | _EXTERNAL_OPERATIONS:
    raise FlowError(
        "delivery.toml: Operationen passen nicht zur Laufzeit"
    )


# Halt des Ausführers (kein Ablaufzustand): der Aufruf endet hier.
_HALT_STATUSES = frozenset(
    {
        "ready_to_finalize",
        "awaiting_input",
        "uncertain",
        "error",
        "passed",
    }
)
_END = "end"


def successors(state: str) -> set[str]:
    """Mögliche Folgezustände laut ``delivery.toml``."""
    return {
        target
        for transition in DELIVERY.outgoing(state)
        for target in targets(DELIVERY, transition)
    }


# Agentenoperationen des Lieferablaufs und die Rolle, die sie ausführt
# (Konfigurationsschlüssel, Verbrauchsbuch, Budget).
_AGENT_ROLES = {"work": "worker", "review": "review"}


class RunResumeError(RuntimeError):
    """Eine Wiederaufnahme passt nicht zum persistierten Laufzustand."""


class EvidenceCollector(Protocol):
    """Erfasst Grenzen und beobachtete Wirkung eines Baus."""

    def prepare(self, task: RunTask, round_id: int) -> object: ...

    def collect(
        self,
        task: RunTask,
        round_id: int,
        base: object,
        run_base: object,
        report: WorkReport,
    ) -> ControllerContext: ...


class RunGraphState(TypedDict):
    run_state: dict[str, object]
    task: dict[str, object]
    round_id: int
    review_sequence: int
    status: str
    open_objection: str | None
    round_base: object | None
    run_base: object | None
    work_report: str | None
    evidence: dict[str, object] | None
    reviewed_refs: dict[str, object] | None
    frozen_result: dict[str, object] | None
    final_result: dict[str, object] | None
    pending_operation: dict[str, object] | None
    decision: dict[str, object] | None
    decision_answer: str | None
    last_error: str | None
    interrupt_payload: NotRequired[dict[str, object] | None]


@dataclass(frozen=True)
class RunResult:
    run_id: str
    status: str
    round_id: int
    phase: Phase
    detail: str | None = None
    operation_id: str | None = None


@dataclass
class RunRuntime:
    """Fuehrt genau einen Laufthread mit SQLite-Checkpoints aus."""

    store: RunStore
    worker: Worker
    reviewer: Reviewer
    evidence_collector: EvidenceCollector
    finalizer: Finalizer
    limits: ProjectionLimits = DEFAULT_PROJECTION_LIMITS
    safety_limits: SafetyLimits = SafetyLimits()

    def __post_init__(self) -> None:
        if (
            isinstance(self.worker, AgentWorker)
            and isinstance(self.reviewer, AgentReviewer)
            and self.worker.session_id == self.reviewer.session_id
        ):
            raise ValueError(
                "Bau und Review brauchen unabhaengige Sitzungen"
            )
        self._invocation_id = uuid.uuid4().hex
        self._ledger = CallLedger(self.store)
        self._quota_baseline = QuotaBaseline(self.store)
        self.store.run_dir.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            self.store.checkpoint_path, check_same_thread=False
        )
        serializer = JsonPlusSerializer(allowed_msgpack_modules=[])
        self._checkpointer = SqliteSaver(
            self._connection, serde=serializer
        )
        self._graph = self._compile_graph()

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> RunRuntime:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start(
        self,
        task: RunTask,
        limits: Limits,
        *,
        manifest_extra: dict[str, object] | None = None,
    ) -> RunResult:
        if not isinstance(limits, Limits):
            raise TypeError("limits muss ein machine.Limits-Wert sein")
        manifest = {
            "schema_version": 1,
            "task": _encode_task(task),
            "limits": asdict(limits),
            "safety_limits": asdict(self.safety_limits),
        }
        if manifest_extra:
            overlap = set(manifest) & set(manifest_extra)
            if overlap:
                raise ValueError(
                    f"reservierte Manifestfelder: {sorted(overlap)}"
                )
            manifest.update(manifest_extra)
        self.store.initialize(manifest)
        initial: RunGraphState = {
            "run_state": encode_run_state(
                RunState(
                    task.run_id,
                    0,
                    MachineState(Phase(DELIVERY.start)),
                    limits,
                )
            ),
            "task": _encode_task(task),
            "round_id": 1,
            "review_sequence": 0,
            "status": "running",
            "open_objection": None,
            "round_base": None,
            "run_base": None,
            "work_report": None,
            "evidence": None,
            "reviewed_refs": None,
            "frozen_result": None,
            "final_result": None,
            "pending_operation": None,
            "decision": None,
            "decision_answer": None,
            "last_error": None,
        }
        if self._snapshot_exists():
            raise RunResumeError(
                f"Lauf {task.run_id} existiert bereits"
            )
        self._invoke(initial)
        return self.result()

    def resume(self, answer: str | None = None) -> RunResult:
        snapshot = self._snapshot()
        state = cast(RunGraphState, snapshot.values)
        if state["status"] == "uncertain":
            return self.result()
        if state["status"] == "passed":
            return self.result()
        if state["status"] == "awaiting_input":
            return self._continue_after_relay(answer)
        if snapshot.interrupts:
            if answer is None or not answer.strip():
                raise RunResumeError(
                    "Wiederaufnahme braucht eine Antwort"
                )
            payload = {
                "run_id": self.store.run_id,
                "answer": answer,
            }
            self._invoke(Command(resume=payload))
        else:
            if answer is not None:
                raise RunResumeError(
                    "dieser Lauf wartet auf keine Antwort"
                )
            self._invoke(None)
        return self.result()

    def _continue_after_relay(self, answer: str | None) -> RunResult:
        """Offene Operation des Boten erneut fahren; die Antwort liegt
        als Datei im Posteingang, nicht in ``--answer``."""
        if answer is not None:
            raise RunResumeError(
                "der Bote legt seine Antwort als Datei ab, nicht per "
                "--answer"
            )
        self._graph.update_state(
            self._config(),
            {"status": "running", "last_error": None},
            as_node=self._current_node(),
        )
        self._invoke(None)
        return self.result()

    def reconcile(
        self, operation_id: str, artifact: object
    ) -> RunResult:
        """Uebernimm ein extern abgeglichenes Ergebnis explizit."""
        state = cast(RunGraphState, self._snapshot().values)
        pending = state.get("pending_operation")
        if state["status"] != "uncertain" or pending is None:
            raise RunResumeError("Lauf hat keine unklare Operation")
        if pending.get("id") != operation_id:
            raise RunResumeError(
                "Abgleich gehoert nicht zur unklaren Operation"
            )
        if pending.get("call_id"):
            try:
                self._ledger.reconcile(pending["call_id"], artifact)
            except SafetyStop as exc:
                raise RunResumeError(str(exc)) from exc
        self.store.write_artifact(operation_id, artifact)
        self._graph.update_state(
            self._config(),
            {"status": "running", "last_error": None},
            as_node=self._current_node(),
        )
        self._invoke(None)
        return self.result()

    def result(self) -> RunResult:
        state = cast(RunGraphState, self._snapshot().values)
        return _decode_result(state)

    def _invoke(self, value: object) -> None:
        run = self._latest_run_state(value)
        maximum_steps = 20 + 12 * (
            run.limits.worker_attempts
            + run.limits.protocol_attempts
            + run.limits.process_retries
        )
        config = {
            "configurable": {"thread_id": self.store.run_id},
            "recursion_limit": maximum_steps,
        }
        self._graph.invoke(value, config)

    def _latest_run_state(self, value: object) -> RunState:
        if isinstance(value, dict) and "run_state" in value:
            return decode_run_state(value["run_state"])
        if self._snapshot_exists():
            state = cast(RunGraphState, self._snapshot().values)
            return decode_run_state(state["run_state"])
        raise RunResumeError("kein persistierter Lauf vorhanden")

    def _snapshot_exists(self) -> bool:
        return bool(self._graph.get_state(self._config()).values)

    def _snapshot(self):
        snapshot = self._graph.get_state(self._config())
        if not snapshot.values:
            raise RunResumeError(f"Lauf {self.store.run_id} fehlt")
        return snapshot

    def _config(self) -> dict[str, object]:
        return _thread_config(self.store.run_id)

    def _compile_graph(self):
        """Ein Graphmodell: jeder Zustand von ``delivery.toml`` ist ein
        Knoten, jede Kante ein möglicher Übergang (``@history``
        aufgelöst). Welche Kante gilt, wählt weiterhin der Ablauf
        (``advance``); der Graph führt sie aus und hält an."""
        graph = StateGraph(RunGraphState)
        for state_id, flow_state in DELIVERY.states.items():
            node = (
                self._wait_node
                if flow_state.kind == WAIT_KIND
                else self._tick
            )
            graph.add_node(state_id, node)
        graph.add_edge(START, DELIVERY.start)
        for state_id in DELIVERY.states:
            graph.add_conditional_edges(
                state_id,
                self._route,
                {
                    **{
                        target: target
                        for target in successors(state_id)
                    },
                    state_id: state_id,
                    _END: END,
                },
            )
        return graph.compile(checkpointer=self._checkpointer)

    @staticmethod
    def _route(state: RunGraphState) -> str:
        """Halt des Ausführers beendet den Aufruf; sonst weiter im
        Knoten der aktuellen Phase (auch derselbe Zustand, solange eine
        Operation läuft oder ein wartender Zustand anhält)."""
        if state["status"] in _HALT_STATUSES:
            return _END
        return decode_run_state(state["run_state"]).state.phase.value

    def _current_node(self) -> str:
        state = cast(RunGraphState, self._snapshot().values)
        return decode_run_state(state["run_state"]).state.phase.value

    def _wait_node(self, state: RunGraphState) -> dict[str, object]:
        """Wartender Zustand: erst den Status setzen (Checkpoint), beim
        nächsten Besuch auf die Antwort von außen warten."""
        phase = decode_run_state(state["run_state"]).state.phase.value
        if state["status"] != phase:
            return {"status": phase}
        return self._wait(state)

    def _tick(self, state: RunGraphState) -> dict[str, object]:
        """Einen Schritt fahren: was zu tun ist, sagt der Ablauf.

        Halt- und Endzustände melden nur ihren Status; sonst liefert
        ``delivery.toml`` die Operation des Zustands (Moore-Ausgabe).
        Sofort erzeugte Ereignisse laufen direkt durch ``advance``,
        externe Wirkungen über eine persistierte Operation."""
        pending = state["pending_operation"]
        if pending is not None:
            return self._progress_operation(state, pending)
        run = decode_run_state(state["run_state"])
        kind = operation(run.state, run.limits)
        if kind is None:
            return {"status": run.state.phase.value}
        if kind == "start":
            return self._transition(run, RunStarted())
        if kind == "task":
            return self._transition(
                run, ControllerTask(_task(state).task)
            )
        if kind == "prepare":
            return self._prepare_worker(state, run)
        if kind == "checkpoint":
            return self._transition(run, CheckpointRecorded())
        return {"pending_operation": self._operation(state, kind)}

    def _prepare_worker(
        self, state: RunGraphState, run: RunState
    ) -> dict[str, object]:
        if state["round_base"] is not None:
            return self._transition(run, WorkerInputsPrepared())
        try:
            base = self.evidence_collector.prepare(
                _task(state), state["round_id"]
            )
        except Exception as exc:
            return self._process_failure(
                state, f"{type(exc).__name__}: {exc}"
            )
        return {
            "round_base": base,
            "run_base": state["run_base"] or base,
        }

    def _operation(
        self, state: RunGraphState, kind: str
    ) -> dict[str, object]:
        run = decode_run_state(state["run_state"])
        if kind in {
            "freeze",
            "finalize_history",
            "verify_final",
            "integrate",
        }:
            operation_id = f"final-{kind}-r{run.revision:04d}"
        elif kind == "review":
            operation_id = (
                f"r{state['round_id']:04d}-{kind}-"
                f"a{state['review_sequence']:04d}"
            )
        else:
            # Jeder relevante Zaehler muss einfliessen: ein
            # tatsaechlich neuer Bau-/Nachweisversuch kann
            # round_id und process_retry unveraendert lassen
            # (z. B. bei einer Protokoll-Wiederholung), wuerde
            # sonst dieselbe operation_id wie der vorige
            # Versuch erhalten und dessen gespeichertes
            # Artefakt faelschlich wiederverwenden.
            counters = run.state.counters
            operation_id = (
                f"r{state['round_id']:04d}-{kind}-"
                f"w{counters.worker_attempt:04d}"
                f"-p{counters.process_retry:04d}"
                f"-t{counters.protocol_attempt:04d}"
            )
        return {"id": operation_id, "kind": kind, "status": "prepared"}

    def _progress_operation(
        self, state: RunGraphState, pending: dict[str, object]
    ) -> dict[str, object]:
        operation_id = cast(str, pending["id"])
        stored = self.store.load_artifact(operation_id)
        if stored is not None:
            return self._accept_artifact(state, pending, stored)
        status = pending["status"]
        if status == "prepared":
            call_id = None
            if pending["kind"] in _AGENT_ROLES and not (
                _is_relay(self._actor(pending))
            ):
                actor = self._actor(pending)
                blocker = self._call_guards(
                    _AGENT_ROLES[pending["kind"]], actor
                )
                if blocker is not None:
                    return self._safety_stop(state, blocker)
                call_id = f"{operation_id}-{uuid.uuid4().hex}"
                try:
                    self._ledger.reserve(
                        call_id,
                        operation_id,
                        isinstance(
                            actor, (AgentWorker, AgentReviewer)
                        ),
                        actor.executor.name
                        if isinstance(
                            actor, (AgentWorker, AgentReviewer)
                        )
                        else None,
                        attribution=self._usage_attribution(
                            state, pending, actor
                        ),
                    )
                except SafetyStop as exc:
                    return self._safety_stop(state, str(exc))
            started = {
                **pending,
                "status": "started",
                "invocation": self._invocation_id,
                "call_id": call_id,
            }
            return {"pending_operation": started}
        if pending.get(
            "invocation"
        ) != self._invocation_id and pending.get("kind") not in {
            "freeze",
            "finalize_history",
            "verify_final",
            "integrate",
        }:
            return {
                "status": "uncertain",
                "last_error": (
                    "Externe Wirkung wurde begonnen, aber kein "
                    "Ergebnis wurde "
                    f"gesichert: {operation_id}"
                ),
            }
        try:
            value = self._metered_operation(state, pending)
        except ManualInputPending as exc:
            return self._await_relay(pending, exc)
        except (AgentTurnError, SafetyStop, PermissionError) as exc:
            return self._safety_stop(state, str(exc))
        except AgentProtocolError as exc:
            return self._protocol_failure(state, str(exc))
        except Exception as exc:
            return self._process_failure(
                state, f"{type(exc).__name__}: {exc}"
            )
        self.store.write_artifact(operation_id, value)
        return self._accept_artifact(state, pending, value)

    def _actor(
        self, pending: dict[str, object]
    ) -> Worker | Reviewer:
        if pending["kind"] == "work":
            return self.worker
        return self.reviewer

    @staticmethod
    def _await_relay(
        pending: dict[str, object], exc: ManualInputPending
    ) -> dict[str, object]:
        """Halt des Ausführers, kein Ablaufzustand: die Operation bleibt
        offen und läuft nach der Antwort des Boten erneut."""
        return {
            "pending_operation": {
                "id": pending["id"],
                "kind": pending["kind"],
                "status": "prepared",
            },
            "status": "awaiting_input",
            "last_error": str(exc),
        }

    def _call_guards(
        self, role: str, actor: Worker | Reviewer
    ) -> str | None:
        """Alle zutreffenden Pausengruende vor einem Aufruf gemeinsam
        ausgeben, keine Kurzschluss-Auswertung: eine erreichte
        Kontextgrenze verdeckt nicht, dass auch das Kontingent knapp
        ist, und umgekehrt (ki-dev-ablauf-dqv)."""
        blockers = [
            blocker
            for blocker in (
                self._context_guard(role, actor),
                self._quota_guard(role, actor),
            )
            if blocker is not None
        ]
        return "; ".join(blockers) if blockers else None

    def _context_guard(
        self, role: str, actor: Worker | Reviewer
    ) -> str | None:
        """Kontextgrenze technisch pruefen, bevor ein Aufruf reserviert
        wird (ki-dev-ablauf-agu).

        Der Adapter liefert nur einen Messwert; Freigabe und Halt
        entscheidet ausschliesslich diese Orchestrierung, nie eine
        Selbsteinschaetzung des Agenten. ``UNSUPPORTED`` (z. B. Codex)
        ist kein Blocker: das ist ein bekannter, dokumentierter
        Adaptergrenzfall, keine ungeklaerte Situation. ``UNAVAILABLE``
        dagegen ist ein Blocker: die Messung ist fuer diesen Executor
        vorgesehen, aber gerade nicht belegbar, und ein unbelegter
        Kontext gilt nicht als klein.

        Ein fehlendes Rollenbudget ist unabhaengig vom Kontextstatus
        keine gueltige Konfiguration: es steuert auch den nativen
        Timeout und die Verbrauchserfassung im Adapter (siehe
        ``CliAdapter.send_turn``/``claude_result``/``codex_result``).
        Ein ``UNSUPPORTED``- oder ``UNAVAILABLE``-Messwert darf das
        deshalb nicht stillschweigend uebertoenen; die Pruefung steht
        vor jeder Fallunterscheidung nach Kontextstatus.
        """
        if not isinstance(actor, (AgentWorker, AgentReviewer)):
            return None
        if actor.budget is None:
            raise ValueError(
                f"{role} (executor={actor.executor.name}, "
                f"session={actor.session_id}): TurnBudget fehlt; "
                "Timeout und Verbrauchserfassung waeren ungueltig"
            )
        measurement = actor.executor.measure_context(actor.session_id)
        origin = (
            f"{role} (executor={actor.executor.name}, "
            f"session={actor.session_id})"
        )
        if measurement.status is ContextStatus.UNAVAILABLE:
            blocker = (
                f"Kontextmessung fuer {origin} nicht verfuegbar: "
                f"{measurement.detail}; kein Aufruf ohne Nachweis"
            )
        elif (
            measurement.status is ContextStatus.MEASURED
            and measurement.tokens >= actor.budget.max_context_tokens
        ):
            blocker = (
                f"Kontextgrenze erreicht fuer {origin}: gemessen "
                f"{measurement.tokens} >= Grenze "
                f"{actor.budget.max_context_tokens} "
                f"(Quelle: {measurement.status.value})"
            )
        else:
            blocker = None
        return blocker

    def _quota_guard(
        self, role: str, actor: Worker | Reviewer
    ) -> str | None:
        """Fuenfstundenkontingent technisch pruefen, bevor ein Aufruf
        reserviert wird (ki-dev-ablauf-hju, ueberarbeitet in dqv).

        Zwei unabhaengige, gemeinsam ausgegebene Pausengruende, keine
        Kurzschluss-Auswertung (eine Pruefung kann die andere nicht
        verdecken):

        1. Aufgaben-Delta-Budget (``actor.budget.
           max_usage_delta_percentage_points``, pro Rolle): wie viele
           Prozentpunkte das beobachtete, kontoweite
           Fuenfstundenkontingent seit der Baseline dieser Rolle
           gewachsen ist (``QuotaBaseline.delta_percent``). Ein
           konservatives Pausesignal, keine exakte Zurechnung --
           paralleler fremder Verbrauch auf demselben Konto zaehlt mit.
        2. Zentrale Schutzreserve (``safety_limits.
           min_remaining_percent``): haelt an, sobald fuer diese Rolle
           kaum noch Kontingent uebrig ist, unabhaengig vom
           Aufgabenbudget.

        Beides ist eine Pause-Schwelle vor dem naechsten Aufruf, keine
        harte Echtzeitgrenze: ein einzelner Aufruf kann sie
        ueberschreiten, da er nicht unterbrochen werden kann.

        Wie bei der Kontextvorpruefung gibt es hier keinen Status, der
        einen Aufruf freigibt, ausser einem tatsaechlichen Messwert:
        fuer das Kontokontingent gibt es keine sichere Annahme "kein
        Nachweis = ok". ``UNSUPPORTED`` blockiert deshalb -- anders als
        bei ``measure_context`` -- ebenso wie ``UNAVAILABLE``, und wird
        als eigene, von "Budget erschoepft" klar unterschiedene Ursache
        gemeldet. Das ist eine bewusste, dokumentierte Betriebsfolge:
        ein Executor ohne verifizierten, verbrauchsfreien Messweg
        (aktuell ``claude-cli``) haelt vor jedem Aufruf an, bis ein
        solcher Messweg existiert und getestet ist.

        ``self._ledger.limits()`` kann bei einem Altlauf ohne
        ``min_remaining_percent`` im Manifest ``SafetyStop`` werfen;
        anders als bei ``_ledger.reserve`` gibt es hier keinen
        umschliessenden ``try/except`` in ``_progress_operation``, die
        Ausnahme wird deshalb hier selbst in einen Blocker-Text
        uebersetzt statt unbehandelt aus dem Graph-Tick zu entkommen.
        """
        if not isinstance(actor, (AgentWorker, AgentReviewer)):
            return None
        try:
            limits = self._ledger.limits()
        except SafetyStop as exc:
            return str(exc)
        measurement = actor.executor.measure_quota(actor.session_id)
        origin = (
            f"{role} (executor={actor.executor.name}, "
            f"session={actor.session_id})"
        )
        if measurement.status is not QuotaStatus.MEASURED:
            return _quota_missing_reason(origin, measurement)
        reasons = [
            reason
            for reason in (
                _quota_reserve_reason(origin, measurement, limits),
                self._quota_delta_reason(
                    origin, measurement, role, actor.budget
                ),
            )
            if reason is not None
        ]
        return "; ".join(reasons) if reasons else None

    def _quota_delta_reason(
        self,
        origin: str,
        measurement: object,
        role: str,
        budget: object,
    ) -> str | None:
        try:
            delta = self._quota_baseline.delta_percent(
                role, measurement.used_percent, measurement.resets_at
            )
        except RunStoreError as exc:
            return f"Kontingent-Basislinie fuer {origin}: {exc}"
        allowed = budget.max_usage_delta_percentage_points
        if delta < allowed:
            return None
        return (
            f"Aufgaben-Delta-Budget erreicht fuer {origin}: "
            f"beobachteter kontoweiter Verbrauch seit Rollenbaseline "
            f"im aktuellen Fenster {delta:g} Prozentpunkte >= Budget "
            f"{allowed:g}"
        )

    def _usage_attribution(
        self, state, pending, actor
    ) -> UsageAttribution:
        # Explicit task identity, never inferred from prose or graph
        # revision.
        binding = self.store.load_manifest().get("usage_task", {})
        if pending["kind"] == "review":
            purpose = UsagePurpose.REVIEW
        elif state["round_id"] > 1:
            purpose = UsagePurpose.REPAIR
        else:
            purpose = UsagePurpose.IMPLEMENTATION
        return UsageAttribution(
            bead_id=binding.get("bead_id"),
            task_revision=binding.get("task_revision"),
            family_id=binding.get("family_id"),
            family_revision=binding.get("family_revision"),
            parent_bead_id=binding.get("parent_bead_id"),
            role=_AGENT_ROLES[pending["kind"]], purpose=purpose,
            session_id=getattr(actor, "session_id", None),
        )

    def _metered_operation(
        self, state: RunGraphState, pending: dict[str, object]
    ) -> object:
        if pending["kind"] not in _AGENT_ROLES or _is_relay(
            self._actor(pending)
        ):
            # Der Bote verbraucht kein Agentenbudget von ki-dev: die
            # Sitzung, in die er die Eingabe trägt, misst ki-dev nicht.
            return self._execute_operation(state, pending)
        call_id = pending.get("call_id")
        if not call_id:
            raise SafetyStop(
                "Agentenaufruf ohne persistierte Budgetreservierung"
            )
        actor = (
            self.worker
            if pending["kind"] == "work"
            else self.reviewer
        )
        try:
            value = self._execute_operation(state, pending)
        except Exception as exc:
            # Verbrauch zuerst verbuchen, ``finish()`` (loescht die
            # "ungeklaert"-Sperre aus ``reserve()``) erst danach: sonst
            # kann eine Reservierung zwischen beiden Schreibvorgaengen
            # -- oder nach einem Prozessabbruch dazwischen -- durch-
            # rutschen, obwohl ein PARTIAL-Beleg sie sperren muesste.
            try:
                self._record_turn_usage(call_id, actor)
            except Exception as usage_exc:
                raise usage_exc from exc
            self._ledger.finish(
                call_id,
                getattr(actor, "last_result", None),
                f"{type(exc).__name__}: {exc}",
            )
            if isinstance(
                actor, (AgentWorker, AgentReviewer)
            ) and not isinstance(exc, AgentProtocolError):
                raise SafetyStop(str(exc)) from exc
            raise
        self._record_turn_usage(call_id, actor)
        self._ledger.finish(
            call_id, getattr(actor, "last_result", None), None
        )
        return value

    def _record_turn_usage(
        self, call_id: str, actor: Worker | Reviewer
    ) -> None:
        """Den vom Adapter aus dem echten Turnergebnis normalisierten
        UsageEvent verbuchen (ki-dev-ablauf-wu0.3): derselbe reale
        CLI-Turn, nicht ein Testfixture. Ein gueltiger, in sich
        konsistenter ``MEASURED``-CALL_TOTAL-Summenbeleg ohne Baseline
        loest laut Messvertrag (``usage.py``,
        ``usage_accounting.reconcile_call``) keinen falschen Konflikt
        aus, solange ``evidence_ref`` -- wie hier -- eindeutig an
        ``call_id`` haengt (siehe tests/test_usage_accounting.py,
        test_claude_call_total_summary_reconciles_with_legacy_usage).
        Das gilt NICHT pauschal fuer jeden CALL_TOTAL-Beleg: ein
        ``PARTIAL``-Beleg (z. B. nicht verifizierte CLI-Version) erzeugt
        ueber ``usage_accounting.counters()`` bewusst den blockierenden
        Gap ``measurement_incomplete`` -- das ist die bestehende,
        konservative Sicherheitsregel, kein Fehler dieser Funktion
        (siehe tests/test_usage_accounting.py,
        test_partial_call_total_keeps_counts_and_blocks_next_reservation).
        Fehlender/nicht messbarer Verbrauch ist fehlende Provenienz,
        keine widerspruechliche Bilanz, und bleibt deshalb unverbucht
        statt einen Fehler auszuloesen.
        """
        result = getattr(actor, "last_result", None)
        event = result.usage_event if result is not None else None
        if event is None or event.status not in (
            UsageStatus.MEASURED,
            UsageStatus.PARTIAL,
        ):
            return
        self._ledger.record_usage(
            call_id, event, f"turn:{call_id}", summary=True
        )

    def _safety_stop(
        self, state: RunGraphState, detail: str
    ) -> dict[str, object]:
        """Technischer Schutzhalt: Kante ``execution_stopped`` des
        Ablaufs, Fortsetzungspunkt ist der aktuelle Zustand."""
        run = decode_run_state(state["run_state"])
        update = self._transition(run, ExecutionStopped(detail))
        return self._guard_halt(state, update, detail)

    def _guard_halt(
        self,
        state: RunGraphState,
        update: dict[str, object],
        detail: str,
    ) -> dict[str, object]:
        """Hülle eines Halts mit Ursache ``execution_guard``."""
        run = decode_run_state(
            cast(dict[str, object], update["run_state"])
        )
        halted = {
            **update,
            "status": "paused_interactive",
            "pending_operation": None,
            "last_error": detail,
            "interrupt_payload": {
                "kind": "escalate",
                "run_id": run.run_id,
                "round_id": state["round_id"],
                "reason": detail,
            },
        }
        return self._write_handoff_if_stopped(state, halted, detail)

    def _write_handoff_if_stopped(
        self,
        state: RunGraphState,
        update: dict[str, object],
        reason: str,
    ) -> dict[str, object]:
        """Persistiere die kompakte Sitzungsuebergabe fuer jeden Halt.

        Gilt fuer jeden Uebergang nach ``PAUSED_INTERACTIVE`` oder
        ``WAITING_DECISION`` -- unabhaengig davon, ob eine
        Maschinengrenze, ein Prozessfehler oder ein Reviewer-Urteil
        (``ESCALATE``/``NEEDS_DECISION``) den Halt ausgeloest hat.
        """
        next_run = decode_run_state(
            cast(dict[str, object], update["run_state"])
        )
        if next_run.state.phase not in WAITING_PHASES:
            return update
        handoff = build_handoff(
            self.store,
            _task(state),
            round_id=state["round_id"],
            phase=next_run.state.phase.value,
            reason=reason,
        )
        self.store.write_handoff(
            f"r{state['round_id']:04d}-rev{next_run.revision:06d}",
            handoff,
        )
        return update

    def _execute_operation(
        self, state: RunGraphState, pending: dict[str, object]
    ) -> object:
        kind = pending["kind"]
        task = _task(state)
        round_id = state["round_id"]
        if kind == "work":
            report = self.worker.work(
                WorkRequest(task, round_id, state["open_objection"])
            )
            return {"summary": report.summary}
        if kind == "evidence":
            report = WorkReport(cast(str, state["work_report"]))
            context = self.evidence_collector.collect(
                task,
                round_id,
                state["round_base"],
                state["run_base"],
                report,
            )
            _validate_context(context, task, round_id)
            projection = project_review_context(
                context, limits=self.limits
            )
            return {
                "context": _context_document(context),
                "projection": {
                    "text": projection.text,
                    "omissions": [
                        asdict(omission)
                        for omission in projection.omissions
                    ],
                },
                "assessment": assess_step_delta(
                    context.step_delta
                ).value,
            }
        if kind == "review":
            evidence = cast(dict[str, object], state["evidence"])
            summary = cast(str, state["work_report"])
            answer = state["decision_answer"]
            if answer:
                summary += f"\n\nGebundene Entscheidung: {answer}"
            from ki_dev.review_context import Omission, ReviewProjection

            omissions = cast(
                list[dict[str, str]], evidence["omissions"]
            )

            projection = ReviewProjection(
                text=cast(str, evidence["text"]),
                omissions=tuple(Omission(**item) for item in omissions),
            )
            raw = self.reviewer.review(
                ReviewRequest(
                    task,
                    round_id,
                    WorkReport(summary),
                    projection,
                    REVIEW_VOCABULARY,
                )
            )
            decision = parse_review_decision(
                raw, run_id=task.run_id, round_id=round_id
            )
            decision = bind_review_decision(decision, task)
            return {
                "raw": raw,
                "decision": _decision_document(decision),
            }
        if kind == "freeze":
            base_refs = cast(dict[str, object], state["run_base"])
            reviewed_refs = cast(
                dict[str, object], state["reviewed_refs"]
            )
            return self.finalizer.freeze(
                source=task.workdir,
                run_id=task.run_id,
                base_refs=base_refs,
                reviewed_refs=reviewed_refs,
            )
        if kind == "finalize_history":
            return self.finalizer.finalize_history(
                cast(dict[str, object], state["frozen_result"])
            )
        if kind == "verify_final":
            return self.finalizer.verify(
                cast(dict[str, object], state["frozen_result"]),
                cast(dict[str, object], state["final_result"]),
            )
        if kind == "integrate":
            return self.finalizer.integrate(
                cast(dict[str, object], state["frozen_result"]),
                cast(dict[str, object], state["final_result"]),
            )
        raise RuntimeError(f"unbekannte Operation {kind!r}")

    def _accept_artifact(
        self,
        state: RunGraphState,
        pending: dict[str, object],
        artifact: object,
    ) -> dict[str, object]:
        if not isinstance(artifact, dict):
            raise RuntimeError("Operationsartefakt ist kein Objekt")
        kind = pending["kind"]
        run = decode_run_state(state["run_state"])
        if kind == "work":
            return {
                **self._transition(run, WorkerCompleted()),
                "work_report": cast(str, artifact["summary"]),
                "pending_operation": None,
                "last_error": None,
            }
        if kind == "evidence":
            assessment = StepDeltaAssessment(
                cast(str, artifact["assessment"])
            )
            projection = cast(dict[str, object], artifact["projection"])
            return {
                **self._transition(run, StepResultCaptured(assessment)),
                "evidence": projection,
                "reviewed_refs": _result_refs(artifact),
                "pending_operation": None,
                "last_error": None,
            }
        if kind == "freeze":
            return {
                **self._transition(run, ReviewedResultFrozen()),
                "frozen_result": artifact,
                "pending_operation": None,
                "last_error": None,
            }
        if kind == "finalize_history":
            return {
                **self._transition(run, HistoryFinalized()),
                "final_result": artifact,
                "pending_operation": None,
                "last_error": None,
            }
        if kind == "verify_final":
            ok = artifact.get("ok") is True
            update = self._transition(run, FinalResultVerified(ok))
            next_run = decode_run_state(
                cast(dict[str, object], update["run_state"])
            )
            detail = cast(str | None, artifact.get("detail"))
            return self._write_handoff_if_stopped(
                state,
                {
                    **update,
                    "pending_operation": None,
                    "status": _status_of(next_run),
                    "last_error": detail,
                },
                detail or "Abschlusspruefung fehlgeschlagen",
            )
        if kind == "integrate":
            ok = artifact.get("ok") is True
            update = self._transition(run, IntegrationCompleted(ok))
            next_run = decode_run_state(
                cast(dict[str, object], update["run_state"])
            )
            detail = cast(str | None, artifact.get("detail"))
            return self._write_handoff_if_stopped(
                state,
                {
                    **update,
                    "pending_operation": None,
                    "status": _status_of(next_run),
                    "last_error": None if ok else detail,
                },
                detail or "Integration fehlgeschlagen",
            )
        decision_doc = cast(dict[str, object], artifact["decision"])
        decision = _decode_decision(decision_doc)
        self.store.write_message(cast(str, pending["id"]), decision_doc)
        update = self._apply_decision(state, run, decision)
        return {
            **update,
            "pending_operation": None,
            "decision": decision_doc,
            "review_sequence": state["review_sequence"] + 1,
        }

    def _apply_decision(
        self,
        state: RunGraphState,
        run: RunState,
        decision: ReviewDecision,
    ) -> dict[str, object]:
        verdict = DELIVERY.verdict(decision.event)
        if verdict is Verdict.CHANGES:
            facts, guard_detail = self._changes_facts(
                run, decision
            )
            update = self._transition(
                run, ControllerChanges(decision.detail), facts=facts
            )
            if _halted_by_guard(update):
                return self._guard_halt(state, update, guard_detail)
            next_run = decode_run_state(
                cast(dict[str, object], update["run_state"])
            )
            if next_run.state.is_stopped:
                return self._write_handoff_if_stopped(
                    state,
                    {**update, "status": _status_of(next_run)},
                    decision.detail,
                )
            return {
                **update,
                "round_id": state["round_id"] + 1,
                "open_objection": decision.detail,
                "round_base": None,
                "work_report": None,
                "evidence": None,
                "decision_answer": None,
            }
        if verdict is Verdict.PASS:
            return self._transition(run, ControllerPass())
        if verdict is Verdict.NEEDS_DECISION:
            return self._write_handoff_if_stopped(
                state,
                {
                    **self._transition(
                        run, ControllerNeedsDecision(decision.detail)
                    ),
                    "interrupt_payload": {
                        "kind": "needs_decision",
                        "run_id": run.run_id,
                        "round_id": state["round_id"],
                        "question": decision.detail,
                    },
                },
                decision.detail,
            )
        return self._write_handoff_if_stopped(
            state,
            {
                **self._transition(
                    run, ControllerEscalate(decision.detail)
                ),
                "interrupt_payload": {
                    "kind": "escalate",
                    "run_id": run.run_id,
                    "round_id": state["round_id"],
                    "reason": decision.detail,
                },
            },
            decision.detail,
        )

    def _changes_facts(
        self, run: RunState, decision: ReviewDecision
    ) -> tuple[frozenset[str], str]:
        """Fakten aus Laufdaten außerhalb des Maschinenzustands
        (Verbrauchsbuch, Beanstandungsverlauf) für die Wächter
        ``changes_refused`` und ``stagnation`` von
        ``delivery.toml``.

        Der Ablauf prüft ``changes_refused`` vor ``stagnation``;
        der zurückgegebene Text beschreibt den ersten zutreffenden."""
        limits = self._ledger.limits()
        if run.state.counters.changes_round >= (
            limits.max_failed_corrections
        ):
            return frozenset({"changes_refused"}), (
                "Korrekturen wiederholt abgelehnt; "
                "Ursache/Loesungsansatz vor weiterem Bau klaeren. "
                + decision.detail
            )
        reason = stagnation_reason(
            self.store,
            verdict=DELIVERY.verdict(decision.event),
            requirement_ref=decision.requirement_ref,
            limit=limits.max_stagnant_changes,
        )
        if reason is not None:
            return frozenset({"stagnation"}), reason
        return frozenset(), decision.detail

    def _protocol_failure(
        self, state: RunGraphState, detail: str
    ) -> dict[str, object]:
        run = decode_run_state(state["run_state"])
        update = self._transition(run, ProtocolError(detail))
        next_run = decode_run_state(
            cast(dict[str, object], update["run_state"])
        )
        return self._write_handoff_if_stopped(
            state,
            {
                **update,
                "pending_operation": None,
                "status": _status_of(next_run),
                "last_error": detail,
            },
            detail,
        )

    def _process_failure(
        self, state: RunGraphState, detail: str
    ) -> dict[str, object]:
        run = decode_run_state(state["run_state"])
        if run.state.phase in FINALIZATION_PHASES:
            update = self._transition(run, FinalizationError(detail))
            return {
                **update,
                "pending_operation": None,
                "status": "error",
                "last_error": detail,
            }
        # Formale Ausgabe → Ereignis: ein gescheiterter Bau-Turn ist
        # ein Worker-Ereignis, jede andere Operation ein Prozessfehler.
        event = (
            WorkerProcessError(detail)
            if operation(run.state, run.limits) == "work"
            else ProcessError(detail)
        )
        update = self._transition(run, event)
        next_run = decode_run_state(
            cast(dict[str, object], update["run_state"])
        )
        next_kind = operation(next_run.state, next_run.limits)
        prepares = next_kind == "prepare"
        return self._write_handoff_if_stopped(
            state,
            {
                **update,
                "pending_operation": None,
                "round_base": None if prepares else state["round_base"],
                "status": _status_of(next_run),
                "last_error": detail,
            },
            detail,
        )

    def _transition(
        self,
        run: RunState,
        event: Event,
        *,
        facts: frozenset[str] = frozenset(),
    ) -> dict[str, object]:
        result = advance(run.state, event, run.limits, facts=facts)
        self._log_transition(run, result)
        return self._replace_run(run, result.state, result.escalation)

    def _log_transition(
        self, run: RunState, result: TransitionResult
    ) -> None:
        """Genommene Kante ins Ereignisprotokoll (seq = neue Revision;
        eine Wiederholung nach Absturz schreibt sie nicht doppelt)."""
        transition = cast(Transition, result.transition)
        self.store.append_event(
            event_record(
                seq=run.revision + 1,
                ts=datetime.now(UTC).isoformat(),
                flow=DELIVERY,
                run_id=run.run_id,
                transition=transition,
                target=result.phase.value,
                adapter=self._adapter_of(run),
            )
        )

    def _adapter_of(self, run: RunState) -> str:
        """Wer das Ereignis geliefert hat: der Adapter der Agenten-
        operation des Quellzustands, sonst ki-dev selbst."""
        kind = operation(run.state, run.limits)
        if kind not in _AGENT_ROLES:
            return "ki-dev"
        return _adapter_name(self._actor({"kind": kind}))

    @staticmethod
    def _replace_run(
        run: RunState,
        state: MachineState,
        escalation: AgentEscalation | MachineEscalation | None,
    ) -> dict[str, object]:
        changed = replace(
            run,
            revision=run.revision + 1,
            state=state,
            escalation=escalation,
        )
        return {"run_state": encode_run_state(changed)}

    def _wait(self, state: RunGraphState) -> dict[str, object]:
        payload = state.get("interrupt_payload")
        answer = interrupt(payload)
        if not isinstance(answer, dict) or set(answer) != {
            "run_id",
            "answer",
        }:
            raise RunResumeError("ungueltige Wiederaufnahme-Huelle")
        if answer["run_id"] != self.store.run_id:
            raise RunResumeError("Antwort gehoert zu fremdem Lauf")
        text = answer["answer"]
        if not isinstance(text, str) or not text.strip():
            raise RunResumeError("Antwort darf nicht leer sein")
        run = decode_run_state(state["run_state"])
        if run.state.phase not in WAITING_PHASES:
            raise RunResumeError("persistierter Lauf wartet nicht")
        resume_point = (
            None
            if run.escalation is None
            else run.escalation.resume_point
        )
        try:
            update = self._transition(
                run, ResumeRequested(resume_point)
            )
        except InvalidTransition as exc:
            raise RunResumeError(
                "pausierter Lauf hat keinen Fortsetzungspunkt"
            ) from exc
        return {
            **update,
            "status": "running",
            "decision_answer": text,
            "decision": None,
            "interrupt_payload": None,
            "last_error": None,
        }


def _adapter_name(actor: object) -> str:
    executor = getattr(actor, "executor", None)
    if executor is not None:
        return str(executor.name)
    if isinstance(actor, ManualRelay):
        return manual.NAME
    if isinstance(actor, (mock.MockWorker, mock.MockReviewer)):
        return mock.NAME
    # Testdoppel und eigene Adapter: ihr Klassenname
    return type(actor).__name__


def _is_relay(actor: object) -> bool:
    return isinstance(actor, ManualRelay)


def _status_of(run: RunState) -> str:
    """Status eines Laufs: der Haltezustand selbst oder ``running``."""
    if run.state.is_stopped:
        return run.state.phase.value
    return "running"


def _halted_by_guard(update: dict[str, object]) -> bool:
    run = decode_run_state(cast(dict[str, object], update["run_state"]))
    return (
        isinstance(run.escalation, MachineEscalation)
        and run.escalation.cause
        is MachineEscalationCause.EXECUTION_GUARD
    )


_STATUS_READ_ATTEMPTS = 3


def read_run_status(store: RunStore) -> RunResult:
    """Lies den zuletzt persistierten Laufstatus rein lesend.

    Der Checkpoint wird nur betrachtet, wenn er bereits existiert. Die
    Kopie entsteht ueber SQLites eigene Online-Backup-API
    (``sqlite3.Connection.backup``) aus einer read-only geoeffneten
    Quellverbindung: das Backup laeuft in einer eigenen
    Lesetransaktion mit Snapshot-Isolation und liefert deshalb immer
    einen tatsaechlich existierenden, in sich konsistenten Zustand --
    nie eine Mischung aus zwei verschiedenen Schreibvorgaengen, wie es
    ein manuelles Kopieren von WAL-/SHM-/Hauptdatei bei einem
    dazwischenliegenden Checkpoint erzeugen koennte. Im Laufverzeichnis
    selbst entsteht dadurch nie eine neue Datei und nie eine
    Schreibwirkung.

    Ein zweiter und dritter Leseversuch mit je frischer Kopie faengt
    eine seltene ``sqlite3.OperationalError`` (z. B. eine sehr kurze
    Sperre) ab, statt einen vollstaendigen, persistierten Lauf
    faelschlich als fehlend zu melden.

    Die gelesene Zustandsstruktur wird beim Dekodieren validiert:
    fehlende oder ungueltige Pflichtfelder (``status``, ``round_id``)
    oder ein ungueltiges ``run_state``-Dokument werden als
    ``RunResumeError`` gemeldet statt als ungefangener
    ``KeyError``/Formatfehler durchzuschlagen.
    """
    if not store.checkpoint_path.exists():
        raise RunResumeError(f"Lauf {store.run_id} fehlt")
    last_error: Exception | None = None
    for _ in range(_STATUS_READ_ATTEMPTS):
        try:
            tuple_ = _read_checkpoint_tuple(store)
        except (sqlite3.DatabaseError, OSError) as exc:
            last_error = exc
            continue
        if tuple_ is None:
            continue
        try:
            state = cast(
                RunGraphState, tuple_.checkpoint["channel_values"]
            )
            return _decode_result(state)
        except (KeyError, TypeError, ValueError) as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise RunResumeError(
            f"Lauf {store.run_id} ist unvollstaendig: {last_error}"
        ) from last_error
    raise RunResumeError(f"Lauf {store.run_id} fehlt")


def _quota_missing_reason(origin: str, measurement: object) -> str:
    detail = f": {measurement.detail}" if measurement.detail else ""
    return (
        f"Fuenfstundenkontingent-Messwert fuer {origin} fehlt "
        f"({measurement.status.value}){detail}; kein Aufruf ohne "
        "Nachweis"
    )


def _quota_reserve_reason(
    origin: str, measurement: object, limits: SafetyLimits
) -> str | None:
    remaining = 100.0 - measurement.used_percent
    if remaining > limits.min_remaining_percent:
        return None
    return (
        f"Schutzreserve unterschritten fuer {origin}: verbleibend "
        f"{remaining:g}% <= Reserve {limits.min_remaining_percent:g}%"
    )


def _read_checkpoint_tuple(store: RunStore):
    with tempfile.TemporaryDirectory() as scratch:
        copy_path = Path(scratch) / store.checkpoint_path.name
        # as_uri() verlangt einen absoluten Pfad; --runs-dir ist im
        # CLI-Standard (".ki-dev/runs") relativ.
        absolute_checkpoint = store.checkpoint_path.resolve()
        source = sqlite3.connect(
            f"{absolute_checkpoint.as_uri()}?mode=ro", uri=True
        )
        try:
            _backup_snapshot(source, copy_path)
        finally:
            source.close()
        connection = sqlite3.connect(copy_path, check_same_thread=False)
        try:
            checkpointer = SqliteSaver(
                connection,
                serde=JsonPlusSerializer(allowed_msgpack_modules=[]),
            )
            return checkpointer.get_tuple(_thread_config(store.run_id))
        finally:
            connection.close()


def _backup_snapshot(
    source: sqlite3.Connection, destination: Path
) -> None:
    """Konsistente Momentaufnahme ueber die SQLite-Online-Backup-API.

    ``backup`` haelt intern eine eigene Lesetransaktion und liest die
    Quelle damit als Snapshot zu genau einem Zeitpunkt, unabhaengig
    davon, wie viele Checkpoints ein Schreiber waehrenddessen ausfuehrt.
    """
    target = sqlite3.connect(destination)
    try:
        source.backup(target)
    finally:
        target.close()


def _thread_config(run_id: str) -> dict[str, object]:
    return {"configurable": {"thread_id": run_id}}


_VALID_RUN_STATUSES = frozenset(
    {
        "running",
        "awaiting_input",
        "waiting_decision",
        "paused_interactive",
        "uncertain",
        "error",
        "passed",
    }
)


def _decode_result(state: RunGraphState) -> RunResult:
    run = decode_run_state(state["run_state"])
    status = state["status"]
    if status not in _VALID_RUN_STATUSES:
        raise RunResumeError(f"unbekannter Laufstatus: {status!r}")
    round_id = state["round_id"]
    if (
        isinstance(round_id, bool)
        or not isinstance(round_id, int)
        or round_id < 1
    ):
        raise RunResumeError(f"ungueltige round_id: {round_id!r}")
    pending = state.get("pending_operation") or {}
    operation_id = cast(str | None, pending.get("id"))
    detail = state.get("last_error")
    if run.escalation is not None:
        cause = str(run.escalation.cause)
        detail = f"{cause}: {detail}" if detail else cause
    return RunResult(
        run_id=run.run_id,
        status=status,
        round_id=round_id,
        phase=run.state.phase,
        detail=detail,
        operation_id=operation_id,
    )


def _encode_task(task: RunTask) -> dict[str, object]:
    return {
        "run_id": task.run_id,
        "task": task.task,
        "sources": list(task.sources),
        "workdir": str(task.workdir),
        "access_profile": task.access_profile,
        "acceptance_criteria": list(task.acceptance_criteria),
        "env": dict(task.env),
    }


def _task(state: RunGraphState) -> RunTask:
    value = state["task"]
    return RunTask(
        run_id=cast(str, value["run_id"]),
        task=cast(str, value["task"]),
        sources=tuple(cast(list[str], value["sources"])),
        workdir=Path(cast(str, value["workdir"])),
        access_profile=cast(str, value["access_profile"]),
        acceptance_criteria=tuple(
            cast(list[str], value["acceptance_criteria"])
        ),
        env=cast(dict[str, str], value["env"]),
    )


def _decision_document(decision: ReviewDecision) -> dict[str, object]:
    return {
        "run_id": decision.run_id,
        "round_id": decision.round_id,
        "event": decision.event,
        "verdict": DELIVERY.verdict(decision.event).value,
        "detail": decision.detail,
        "requirement_ref": decision.requirement_ref,
    }


def _decode_decision(value: dict[str, object]) -> ReviewDecision:
    return ReviewDecision(
        cast(str, value["run_id"]),
        cast(int, value["round_id"]),
        cast(str, value["event"]),
        cast(str, value["detail"]),
        cast("str | None", value["requirement_ref"]),
    )


def _validate_context(
    context: ControllerContext, task: RunTask, round_id: int
) -> None:
    if context.task != task.task:
        raise AgentProtocolError(
            "Nachweiskontext gehoert zu fremdem Auftrag"
        )
    if context.round_status.current != round_id:
        raise AgentProtocolError(
            "Nachweiskontext gehoert zu fremder Runde"
        )


def _context_document(context: ControllerContext) -> dict[str, object]:
    """JSON-Nachweis mit Referenzen, Deltas, Checks und Runde."""
    return cast(
        dict[str, object], json.loads(json.dumps(asdict(context)))
    )


def _result_refs(artifact: dict[str, object]) -> dict[str, object]:
    """Extrahiere die Referenzen des dem Reviewer gezeigten Deltas."""
    try:
        context = cast(dict[str, object], artifact["context"])
        step = cast(dict[str, object], context["step_delta"])
        result: dict[str, object] = {}
        for medium in ("git", "beads"):
            delta = cast(dict[str, object], step[medium])
            boundary = cast(dict[str, object], delta["boundary"])
            ref = boundary["result"]
            if not isinstance(ref, dict):
                raise TypeError
            result[medium] = ref
        return result
    except (KeyError, TypeError) as exc:
        raise AgentProtocolError(
            "Nachweisartefakt enthaelt keine Ergebnisreferenzen"
        ) from exc


@dataclass(frozen=True)
class StaticEvidenceCollector:
    """Einfacher Collector fuer kontrollierte Einbettungen und Tests."""

    contexts: tuple[ControllerContext, ...]

    def prepare(self, task: RunTask, round_id: int) -> object:
        return {"run_id": task.run_id, "round_id": round_id}

    def collect(
        self,
        task: RunTask,
        round_id: int,
        base: object,
        run_base: object,
        report: WorkReport,
    ) -> ControllerContext:
        del task, base, run_base, report
        try:
            return self.contexts[round_id - 1]
        except IndexError as exc:
            raise RuntimeError(
                f"kein Kontext fuer Runde {round_id}"
            ) from exc
