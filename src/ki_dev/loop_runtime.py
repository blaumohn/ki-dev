"""Persistente LangGraph-Huelle fuer den begrenzten Bau--Review-Loop."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import NotRequired, Protocol, TypedDict, cast

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ki_dev.deltas import (
    ControllerContext,
    StepDeltaAssessment,
    assess_step_delta,
)
from ki_dev.executors.contract import ContextStatus, QuotaStatus
from ki_dev.loop import (
    AgentBuildMode,
    AgentReviewer,
    AgentTurnError,
    BuildMode,
    BuildReport,
    BuildRequest,
    LoopProtocolError,
    LoopTask,
    ReviewAction,
    ReviewDecision,
    Reviewer,
    ReviewRequest,
    bind_review_decision,
    parse_review_decision,
)
from ki_dev.loop_safety import (
    CallLedger,
    QuotaBaseline,
    SafetyLimits,
    SafetyStop,
    stagnation_reason,
)
from ki_dev.machine import (
    AgentEscalation,
    CheckpointRecorded,
    ControllerChanges,
    ControllerEscalate,
    ControllerNeedsDecision,
    ControllerPass,
    ControllerTask,
    Event,
    FinalizationError,
    FinalResultVerified,
    HistoryFinalized,
    IntegrationCompleted,
    Limits,
    MachineEscalation,
    MachineEscalationCause,
    MachineState,
    Phase,
    ProtocolError,
    ReviewedResultFrozen,
    RunStarted,
    RunState,
    StepResultCaptured,
    WorkerCompleted,
    WorkerInputsPrepared,
    WorkerProcessError,
    advance,
    decode_run_state,
    encode_run_state,
)
from ki_dev.repository_finalization import Finalizer
from ki_dev.review_context import (
    DEFAULT_PROJECTION_LIMITS,
    ProjectionLimits,
    project_review_context,
)
from ki_dev.run_store import RunStore, RunStoreError
from ki_dev.session_handoff import build_handoff
from ki_dev.usage import UsageStatus
from ki_dev.usage_accounting import UsageAttribution, UsagePurpose


class LoopResumeError(RuntimeError):
    """Eine Wiederaufnahme passt nicht zum persistierten Laufzustand."""


class EvidenceCollector(Protocol):
    """Erfasst Grenzen und beobachtete Wirkung eines Baus."""

    def prepare(self, task: LoopTask, round_id: int) -> object: ...

    def collect(
        self,
        task: LoopTask,
        round_id: int,
        base: object,
        run_base: object,
        report: BuildReport,
    ) -> ControllerContext: ...


class LoopGraphState(TypedDict):
    run_state: dict[str, object]
    task: dict[str, object]
    round_id: int
    review_sequence: int
    status: str
    open_objection: str | None
    round_base: object | None
    run_base: object | None
    build_report: str | None
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
class LoopRunResult:
    run_id: str
    status: str
    round_id: int
    phase: Phase
    detail: str | None = None
    operation_id: str | None = None


@dataclass
class LoopRuntime:
    """Fuehrt genau einen Laufthread mit SQLite-Checkpoints aus."""

    store: RunStore
    builder: BuildMode
    reviewer: Reviewer
    evidence_collector: EvidenceCollector
    finalizer: Finalizer
    limits: ProjectionLimits = DEFAULT_PROJECTION_LIMITS
    safety_limits: SafetyLimits = SafetyLimits()

    def __post_init__(self) -> None:
        if (
            isinstance(self.builder, AgentBuildMode)
            and isinstance(self.reviewer, AgentReviewer)
            and self.builder.session_id == self.reviewer.session_id
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

    def __enter__(self) -> LoopRuntime:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start(
        self,
        task: LoopTask,
        limits: Limits,
        *,
        manifest_extra: dict[str, object] | None = None,
    ) -> LoopRunResult:
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
        initial: LoopGraphState = {
            "run_state": encode_run_state(
                RunState(
                    task.run_id, 0, MachineState(Phase.START), limits
                )
            ),
            "task": _encode_task(task),
            "round_id": 1,
            "review_sequence": 0,
            "status": "running",
            "open_objection": None,
            "round_base": None,
            "run_base": None,
            "build_report": None,
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
            raise LoopResumeError(
                f"Lauf {task.run_id} existiert bereits"
            )
        self._invoke(initial)
        return self.result()

    def resume(self, answer: str | None = None) -> LoopRunResult:
        snapshot = self._snapshot()
        state = cast(LoopGraphState, snapshot.values)
        if state["status"] == "uncertain":
            return self.result()
        if state["status"] == "passed":
            return self.result()
        if snapshot.interrupts:
            if answer is None or not answer.strip():
                raise LoopResumeError(
                    "Wiederaufnahme braucht eine Antwort"
                )
            payload = {
                "run_id": self.store.run_id,
                "answer": answer,
            }
            self._invoke(Command(resume=payload))
        else:
            if answer is not None:
                raise LoopResumeError(
                    "dieser Lauf wartet auf keine Antwort"
                )
            self._invoke(None)
        return self.result()

    def reconcile(
        self, operation_id: str, artifact: object
    ) -> LoopRunResult:
        """Uebernimm ein extern abgeglichenes Ergebnis explizit."""
        state = cast(LoopGraphState, self._snapshot().values)
        pending = state.get("pending_operation")
        if state["status"] != "uncertain" or pending is None:
            raise LoopResumeError("Lauf hat keine unklare Operation")
        if pending.get("id") != operation_id:
            raise LoopResumeError(
                "Abgleich gehoert nicht zur unklaren Operation"
            )
        if pending.get("call_id"):
            try:
                self._ledger.reconcile(pending["call_id"], artifact)
            except SafetyStop as exc:
                raise LoopResumeError(str(exc)) from exc
        self.store.write_artifact(operation_id, artifact)
        self._graph.update_state(
            self._config(),
            {"status": "running", "last_error": None},
            as_node="tick",
        )
        self._invoke(None)
        return self.result()

    def result(self) -> LoopRunResult:
        state = cast(LoopGraphState, self._snapshot().values)
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
            state = cast(LoopGraphState, self._snapshot().values)
            return decode_run_state(state["run_state"])
        raise LoopResumeError("kein persistierter Lauf vorhanden")

    def _snapshot_exists(self) -> bool:
        return bool(self._graph.get_state(self._config()).values)

    def _snapshot(self):
        snapshot = self._graph.get_state(self._config())
        if not snapshot.values:
            raise LoopResumeError(f"Lauf {self.store.run_id} fehlt")
        return snapshot

    def _config(self) -> dict[str, object]:
        return _thread_config(self.store.run_id)

    def _compile_graph(self):
        graph = StateGraph(LoopGraphState)
        graph.add_node("tick", self._tick)
        graph.add_node("wait", self._wait)
        graph.add_edge(START, "tick")
        graph.add_conditional_edges(
            "tick",
            self._route,
            {"tick": "tick", "wait": "wait", "end": END},
        )
        graph.add_edge("wait", "tick")
        return graph.compile(checkpointer=self._checkpointer)

    @staticmethod
    def _route(state: LoopGraphState) -> str:
        if state["status"] in {
            "waiting_decision",
            "paused_interactive",
        }:
            return "wait"
        if state["status"] in {
            "ready_to_finalize",
            "uncertain",
            "error",
            "passed",
        }:
            return "end"
        return "tick"

    def _tick(self, state: LoopGraphState) -> dict[str, object]:
        pending = state["pending_operation"]
        if pending is not None:
            return self._progress_operation(state, pending)
        run = decode_run_state(state["run_state"])
        phase = run.state.phase
        if phase is Phase.START:
            return self._transition(run, RunStarted())
        if phase is Phase.CONTROLLER_STEP:
            if run.state.checkpointed_result:
                return {
                    "pending_operation": self._operation(
                        state, "review"
                    )
                }
            return self._transition(
                run, ControllerTask(_task(state).task)
            )
        if phase is Phase.WORKER_STEP_PREPARE:
            if state["round_base"] is None:
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
            return self._transition(run, WorkerInputsPrepared())
        if phase is Phase.WORKER_STEP:
            return {
                "pending_operation": self._operation(state, "build")
            }
        if phase is Phase.CAPTURE_STEP_RESULT:
            return {
                "pending_operation": self._operation(state, "evidence")
            }
        if phase is Phase.CHECKPOINT:
            return self._transition(run, CheckpointRecorded())
        if phase is Phase.FREEZE_REVIEWED_RESULT:
            return {
                "pending_operation": self._operation(state, "freeze")
            }
        if phase is Phase.FINALIZE_HISTORY:
            return {
                "pending_operation": self._operation(
                    state, "finalize_history"
                )
            }
        if phase is Phase.VERIFY_FINAL_RESULT:
            return {
                "pending_operation": self._operation(
                    state, "verify_final"
                )
            }
        if phase is Phase.FAST_FORWARD_INTEGRATE:
            return {
                "pending_operation": self._operation(state, "integrate")
            }
        if phase is Phase.PASSED:
            return {"status": "passed"}
        if phase is Phase.WAITING_DECISION:
            return {"status": "waiting_decision"}
        if phase is Phase.PAUSED_INTERACTIVE:
            return {"status": "paused_interactive"}
        return {
            "status": "error",
            "last_error": (
                f"Phase {phase.value} gehoert nicht zu Schnitt 2"
            ),
        }

    def _operation(
        self, state: LoopGraphState, kind: str
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
        self, state: LoopGraphState, pending: dict[str, object]
    ) -> dict[str, object]:
        operation_id = cast(str, pending["id"])
        stored = self.store.load_artifact(operation_id)
        if stored is not None:
            return self._accept_artifact(state, pending, stored)
        status = pending["status"]
        if status == "prepared":
            call_id = None
            if pending["kind"] in {"build", "review"}:
                actor = (
                    self.builder
                    if pending["kind"] == "build"
                    else self.reviewer
                )
                blocker = self._call_guards(pending["kind"], actor)
                if blocker is not None:
                    return self._safety_stop(state, blocker)
                call_id = f"{operation_id}-{uuid.uuid4().hex}"
                try:
                    self._ledger.reserve(
                        call_id,
                        operation_id,
                        isinstance(
                            actor, (AgentBuildMode, AgentReviewer)
                        ),
                        actor.executor.name
                        if isinstance(
                            actor, (AgentBuildMode, AgentReviewer)
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
        except (AgentTurnError, SafetyStop, PermissionError) as exc:
            return self._safety_stop(state, str(exc))
        except LoopProtocolError as exc:
            return self._protocol_failure(state, str(exc))
        except Exception as exc:
            return self._process_failure(
                state, f"{type(exc).__name__}: {exc}"
            )
        self.store.write_artifact(operation_id, value)
        return self._accept_artifact(state, pending, value)

    def _call_guards(
        self, role: str, actor: BuildMode | Reviewer
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
        self, role: str, actor: BuildMode | Reviewer
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
        if not isinstance(actor, (AgentBuildMode, AgentReviewer)):
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
        self, role: str, actor: BuildMode | Reviewer
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
        if not isinstance(actor, (AgentBuildMode, AgentReviewer)):
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
            role=pending["kind"], purpose=purpose,
            session_id=getattr(actor, "session_id", None),
        )

    def _metered_operation(
        self, state: LoopGraphState, pending: dict[str, object]
    ) -> object:
        if pending["kind"] not in {"build", "review"}:
            return self._execute_operation(state, pending)
        call_id = pending.get("call_id")
        if not call_id:
            raise SafetyStop(
                "Agentenaufruf ohne persistierte Budgetreservierung"
            )
        actor = (
            self.builder
            if pending["kind"] == "build"
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
                actor, (AgentBuildMode, AgentReviewer)
            ) and not isinstance(exc, LoopProtocolError):
                raise SafetyStop(str(exc)) from exc
            raise
        self._record_turn_usage(call_id, actor)
        self._ledger.finish(
            call_id, getattr(actor, "last_result", None), None
        )
        return value

    def _record_turn_usage(
        self, call_id: str, actor: BuildMode | Reviewer
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
        self, state: LoopGraphState, detail: str
    ) -> dict[str, object]:
        run = decode_run_state(state["run_state"])
        escalation = MachineEscalation(
            MachineEscalationCause.EXECUTION_GUARD,
            run.state.phase,
        )
        update = {
            **self._replace_run(
                run,
                run.state.moved_to(Phase.PAUSED_INTERACTIVE),
                escalation,
            ),
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
        return self._write_handoff_if_stopped(state, update, detail)

    def _write_handoff_if_stopped(
        self,
        state: LoopGraphState,
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
        if next_run.state.phase not in (
            Phase.PAUSED_INTERACTIVE,
            Phase.WAITING_DECISION,
        ):
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
        self, state: LoopGraphState, pending: dict[str, object]
    ) -> object:
        kind = pending["kind"]
        task = _task(state)
        round_id = state["round_id"]
        if kind == "build":
            report = self.builder.build(
                BuildRequest(task, round_id, state["open_objection"])
            )
            return {"summary": report.summary}
        if kind == "evidence":
            report = BuildReport(cast(str, state["build_report"]))
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
            summary = cast(str, state["build_report"])
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
                    BuildReport(summary),
                    projection,
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
        state: LoopGraphState,
        pending: dict[str, object],
        artifact: object,
    ) -> dict[str, object]:
        if not isinstance(artifact, dict):
            raise RuntimeError("Operationsartefakt ist kein Objekt")
        kind = pending["kind"]
        run = decode_run_state(state["run_state"])
        if kind == "build":
            return {
                **self._transition(run, WorkerCompleted()),
                "build_report": cast(str, artifact["summary"]),
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
                    "status": "paused_interactive"
                    if next_run.state.phase is Phase.PAUSED_INTERACTIVE
                    else "running",
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
                    "status": "passed"
                    if next_run.state.phase is Phase.PASSED
                    else "paused_interactive",
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
        state: LoopGraphState,
        run: RunState,
        decision: ReviewDecision,
    ) -> dict[str, object]:
        if decision.action is ReviewAction.CHANGES:
            limits = self._ledger.limits()
            if run.state.counters.changes_round >= (
                limits.max_failed_corrections
            ):
                return self._safety_stop(
                    state,
                    "Korrekturen wiederholt abgelehnt; "
                    "Ursache/Loesungsansatz vor weiterem Bau klaeren. "
                    + decision.detail,
                )
            reason = stagnation_reason(
                self.store,
                action=decision.action.value,
                requirement_ref=decision.requirement_ref,
                limit=limits.max_stagnant_changes,
            )
            if reason is not None:
                return self._safety_stop(state, reason)
            update = self._transition(
                run, ControllerChanges(decision.detail)
            )
            next_run = decode_run_state(
                cast(dict[str, object], update["run_state"])
            )
            if next_run.state.phase is Phase.PAUSED_INTERACTIVE:
                return self._write_handoff_if_stopped(
                    state,
                    {**update, "status": "paused_interactive"},
                    decision.detail,
                )
            return {
                **update,
                "round_id": state["round_id"] + 1,
                "open_objection": decision.detail,
                "round_base": None,
                "build_report": None,
                "evidence": None,
                "decision_answer": None,
            }
        if decision.action is ReviewAction.PASS:
            return self._transition(run, ControllerPass())
        if decision.action is ReviewAction.NEEDS_DECISION:
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

    def _protocol_failure(
        self, state: LoopGraphState, detail: str
    ) -> dict[str, object]:
        run = decode_run_state(state["run_state"])
        update = self._transition(run, ProtocolError(detail))
        next_run = decode_run_state(
            cast(dict[str, object], update["run_state"])
        )
        status = (
            "paused_interactive"
            if next_run.state.phase is Phase.PAUSED_INTERACTIVE
            else "running"
        )
        return self._write_handoff_if_stopped(
            state,
            {
                **update,
                "pending_operation": None,
                "status": status,
                "last_error": detail,
            },
            detail,
        )

    def _process_failure(
        self, state: LoopGraphState, detail: str
    ) -> dict[str, object]:
        run = decode_run_state(state["run_state"])
        if run.state.phase in {
            Phase.FREEZE_REVIEWED_RESULT,
            Phase.FINALIZE_HISTORY,
            Phase.VERIFY_FINAL_RESULT,
            Phase.FAST_FORWARD_INTEGRATE,
        }:
            update = self._transition(run, FinalizationError(detail))
            return {
                **update,
                "pending_operation": None,
                "status": "error",
                "last_error": detail,
            }
        if run.state.phase is Phase.WORKER_STEP:
            update = self._transition(run, WorkerProcessError(detail))
        else:
            update = self._manual_process_failure(run)
        next_run = decode_run_state(
            cast(dict[str, object], update["run_state"])
        )
        paused = next_run.state.phase is Phase.PAUSED_INTERACTIVE
        return self._write_handoff_if_stopped(
            state,
            {
                **update,
                "pending_operation": None,
                "round_base": None
                if next_run.state.phase is Phase.WORKER_STEP_PREPARE
                else state["round_base"],
                "status": "paused_interactive" if paused else "running",
                "last_error": detail,
            },
            detail,
        )

    def _manual_process_failure(
        self, run: RunState
    ) -> dict[str, object]:
        counters = run.state.counters
        if counters.process_retry >= run.limits.process_retries:
            escalation = MachineEscalation(
                MachineEscalationCause.PROCESS_RETRIES_EXHAUSTED,
                run.state.phase,
            )
            state = run.state.moved_to(Phase.PAUSED_INTERACTIVE)
            return self._replace_run(run, state, escalation)
        state = run.state.moved_to(
            run.state.phase, counters=counters.retried_process()
        )
        return self._replace_run(run, state, None)

    def _transition(
        self, run: RunState, event: Event
    ) -> dict[str, object]:
        result = advance(run.state, event, run.limits)
        return self._replace_run(run, result.state, result.escalation)

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

    def _wait(self, state: LoopGraphState) -> dict[str, object]:
        payload = state.get("interrupt_payload")
        answer = interrupt(payload)
        if not isinstance(answer, dict) or set(answer) != {
            "run_id",
            "answer",
        }:
            raise LoopResumeError("ungueltige Wiederaufnahme-Huelle")
        if answer["run_id"] != self.store.run_id:
            raise LoopResumeError("Antwort gehoert zu fremdem Lauf")
        text = answer["answer"]
        if not isinstance(text, str) or not text.strip():
            raise LoopResumeError("Antwort darf nicht leer sein")
        run = decode_run_state(state["run_state"])
        if run.state.phase is Phase.WAITING_DECISION:
            resumed = run.state.moved_to(Phase.CONTROLLER_STEP)
        elif run.state.phase is Phase.PAUSED_INTERACTIVE:
            if run.escalation is None:
                raise LoopResumeError(
                    "pausierter Lauf hat keinen Fortsetzungspunkt"
                )
            resumed = run.state.moved_to(run.escalation.resume_point)
        else:
            raise LoopResumeError("persistierter Lauf wartet nicht")
        return {
            **self._replace_run(run, resumed, None),
            "status": "running",
            "decision_answer": text,
            "decision": None,
            "interrupt_payload": None,
            "last_error": None,
        }


_STATUS_READ_ATTEMPTS = 3


def read_run_status(store: RunStore) -> LoopRunResult:
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
    ``LoopResumeError`` gemeldet statt als ungefangener
    ``KeyError``/Formatfehler durchzuschlagen.
    """
    if not store.checkpoint_path.exists():
        raise LoopResumeError(f"Lauf {store.run_id} fehlt")
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
                LoopGraphState, tuple_.checkpoint["channel_values"]
            )
            return _decode_result(state)
        except (KeyError, TypeError, ValueError) as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise LoopResumeError(
            f"Lauf {store.run_id} ist unvollstaendig: {last_error}"
        ) from last_error
    raise LoopResumeError(f"Lauf {store.run_id} fehlt")


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
        "waiting_decision",
        "paused_interactive",
        "uncertain",
        "error",
        "passed",
    }
)


def _decode_result(state: LoopGraphState) -> LoopRunResult:
    run = decode_run_state(state["run_state"])
    status = state["status"]
    if status not in _VALID_RUN_STATUSES:
        raise LoopResumeError(f"unbekannter Laufstatus: {status!r}")
    round_id = state["round_id"]
    if (
        isinstance(round_id, bool)
        or not isinstance(round_id, int)
        or round_id < 1
    ):
        raise LoopResumeError(f"ungueltige round_id: {round_id!r}")
    pending = state.get("pending_operation") or {}
    operation_id = cast(str | None, pending.get("id"))
    detail = state.get("last_error")
    if run.escalation is not None:
        cause = str(run.escalation.cause)
        detail = f"{cause}: {detail}" if detail else cause
    return LoopRunResult(
        run_id=run.run_id,
        status=status,
        round_id=round_id,
        phase=run.state.phase,
        detail=detail,
        operation_id=operation_id,
    )


def _encode_task(task: LoopTask) -> dict[str, object]:
    return {
        "run_id": task.run_id,
        "task": task.task,
        "sources": list(task.sources),
        "workdir": str(task.workdir),
        "access_profile": task.access_profile,
        "acceptance_criteria": list(task.acceptance_criteria),
        "env": dict(task.env),
    }


def _task(state: LoopGraphState) -> LoopTask:
    value = state["task"]
    return LoopTask(
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
        "action": decision.action.value,
        "detail": decision.detail,
        "requirement_ref": decision.requirement_ref,
    }


def _decode_decision(value: dict[str, object]) -> ReviewDecision:
    return ReviewDecision(
        cast(str, value["run_id"]),
        cast(int, value["round_id"]),
        ReviewAction(cast(str, value["action"])),
        cast(str, value["detail"]),
        cast("str | None", value["requirement_ref"]),
    )


def _validate_context(
    context: ControllerContext, task: LoopTask, round_id: int
) -> None:
    if context.task != task.task:
        raise LoopProtocolError(
            "Nachweiskontext gehoert zu fremdem Auftrag"
        )
    if context.round_status.current != round_id:
        raise LoopProtocolError(
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
        raise LoopProtocolError(
            "Nachweisartefakt enthaelt keine Ergebnisreferenzen"
        ) from exc


@dataclass(frozen=True)
class StaticEvidenceCollector:
    """Einfacher Collector fuer kontrollierte Einbettungen und Tests."""

    contexts: tuple[ControllerContext, ...]

    def prepare(self, task: LoopTask, round_id: int) -> object:
        return {"run_id": task.run_id, "round_id": round_id}

    def collect(
        self,
        task: LoopTask,
        round_id: int,
        base: object,
        run_base: object,
        report: BuildReport,
    ) -> ControllerContext:
        del task, base, run_base, report
        try:
            return self.contexts[round_id - 1]
        except IndexError as exc:
            raise RuntimeError(
                f"kein Kontext fuer Runde {round_id}"
            ) from exc
