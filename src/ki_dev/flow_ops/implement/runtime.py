"""Laufzeit des Ausführers: fährt implement.toml bis zum Halt.

Eine deklarierte Maschine: der Lauf (``runner/run.toml``,
:class:`~ki_dev.flow_ops.implement.run_machine.RunMachine`) als
parallele Statechart mit dem Ablauf (``implement.toml``) als Region
neben der offenen Operation und dem Halt. Die Schleife ist synchron:
ein Schritt sendet Ereignisse an die Maschine, externe Wirkung
(Agent, Nachweis, Abschlussweg) läuft außerhalb davon. Vor der
Wirkung wird die Absicht gespeichert, danach das Ergebnis
(Zwei-Schreib-Protokoll); nach jedem Schritt ersetzt
``RunStore.save_record`` den Datensatz atomar. Ein Halt beendet den
Aufruf, ``resume`` liest den Datensatz.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from ki_dev.adapter.agent import (
    AgentReviewer,
    AgentWorker,
)
from ki_dev.adapter.contract import (
    AgentTurnError,
    AnswerPending,
    Reviewer,
    RunTask,
    Worker,
    WorkReport,
)
from ki_dev.adapter.executors.contract import (
    ContextStatus,
    Measure,
    QuotaStatus,
)
from ki_dev.deltas import (
    ControllerContext,
)
from ki_dev.flow.binding import project
from ki_dev.flow.model import (
    FlowError,
    Verdict,
)
from ki_dev.flow.model import Operation as FlowOperation
from ki_dev.flow_ops.implement.decisions import (
    changes_task,
    decision_document,
)
from ki_dev.flow_ops.implement.machine import (
    EVENT_TYPES,
    IMPLEMENT,
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
    InvalidTransition,
    Limits,
    MachineEscalation,
    MachineEscalationCause,
    MachineState,
    Phase,
    ProtocolError,
    ResumeRequested,
    RunStarted,
    RunState,
    RunStateFormatError,
    WorkerInputsPrepared,
    decode_run_state,
    encode_run_state,
    operation,
    operation_of,
)
from ki_dev.flow_ops.implement.ops import (
    ImplementationOperations,
    decode_operation_event,
    failed_checks,
)
from ki_dev.flow_ops.implement.record import (
    RunData,
    RunRecordError,
    decode_record,
    encode_record,
)
from ki_dev.flow_ops.implement.review_output import (
    ReviewDecision,
)
from ki_dev.flow_ops.implement.run_machine import (
    Operation,
    RunMachine,
    Step,
)
from ki_dev.fsm import RecordError, TransitionNotAllowed
from ki_dev.repository_finalization import Finalizer
from ki_dev.review_context import (
    DEFAULT_PROJECTION_LIMITS,
    ProjectionLimits,
)
from ki_dev.run_store import RunStore, RunStoreError
from ki_dev.runner.bound import BoundOperations
from ki_dev.runner.events import ABLAUF, event_record, run_event_record
from ki_dev.runner.review_output import (
    AgentProtocolError,
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

# Fortschritt fuer ``ki-dev -f implement --verbose``.
_log = logging.getLogger("ki_dev.run")

# Operationen aus ``implement.toml``: sofort erzeugte Ereignisse
# (``_step``) und gespeicherte externe Wirkungen
# (``_execute_operation``). Beide Mengen zusammen müssen genau das
# Vokabular des Ablaufs sein.
_IMMEDIATE_OPERATIONS = frozenset(
    {"start", "task", "prepare", "checkpoint"}
)
_EXTERNAL_OPERATIONS = frozenset(IMPLEMENT.bindings)
if (
    set(IMPLEMENT.vocabulary.operations)
    != _IMMEDIATE_OPERATIONS | _EXTERNAL_OPERATIONS
):
    raise FlowError(
        "implement.toml: Operationen passen nicht zur Laufzeit"
    )

# Zustandsarten, deren Erreichen der Lauf-Maschine als Halt gemeldet
# wird (Ereignis = Name des Zustands).
# Agentenoperationen des Umsetzungsablaufs und die Rolle, die sie
# ausführt (Konfigurationsschlüssel, Verbrauchsbuch, Budget).
_AGENT_ROLES = {
    name: b.role
    for name, b in IMPLEMENT.bindings.items()
    if b.role is not None
}
# Datensatz aus der Zeit vor python-statemachine (LangGraph).
_LANGGRAPH_CHECKPOINT = "checkpoints.sqlite"


class RunResumeError(RuntimeError):
    """Eine Wiederaufnahme passt nicht zum gespeicherten Lauf."""


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

    def adopt_issue_change(
        self, task: RunTask, refs: object, issues: frozenset[str]
    ) -> object: ...


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
    """Fährt genau einen Lauf als einziger Schreiber seines
    Datensatzes."""

    store: RunStore
    worker: Worker
    reviewer: Reviewer
    evidence_collector: EvidenceCollector
    finalizer: Finalizer
    limits: ProjectionLimits = DEFAULT_PROJECTION_LIMITS
    safety_limits: SafetyLimits = SafetyLimits()

    def __post_init__(self) -> None:
        sessions = (
            getattr(self.worker, "session_id", None),
            getattr(self.reviewer, "session_id", None),
        )
        if None not in sessions and sessions[0] == sessions[1]:
            raise ValueError(
                "Bau und Review brauchen unabhaengige Sitzungen"
            )
        self._operations = BoundOperations(
            IMPLEMENT.bindings,
            ImplementationOperations(
                self.worker,
                self.reviewer,
                self.evidence_collector,
                self.finalizer,
                self.limits,
            ).catalog(),
        )
        self._ledger = CallLedger(self.store)
        self._quota_baseline = QuotaBaseline(self.store)
        try:
            self._writer = self.store.acquire_writer()
        except RunStoreError as exc:
            raise RunResumeError(str(exc)) from exc
        self._lauf = RunMachine()
        self._data: RunData | None = None

    def close(self) -> None:
        self._writer.close()

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
        if self.store.load_record() is not None:
            raise RunResumeError(
                f"Lauf {task.run_id} existiert bereits"
            )
        self.store.initialize(manifest)
        self._lauf = RunMachine()
        self._data = {
            "run_state": encode_run_state(
                RunState(
                    task.run_id,
                    0,
                    MachineState(Phase(IMPLEMENT.start)),
                    limits,
                )
            ),
            "task": _encode_task(task),
            "round_id": 1,
            "review_sequence": 0,
            "open_objection": None,
            "round_base": None,
            "run_base": None,
            "work_report": None,
            "evidence": None,
            "reviewed_refs": None,
            "frozen_result": None,
            "final_result": None,
            "decision": None,
            "decisions": [],
            "last_error": None,
            "logged": 0,
        }
        self._drive()
        return self.result()

    def resume(
        self, answer: str | None = None, task: RunTask | None = None
    ) -> RunResult:
        """Lauf fortsetzen: ohne Entscheidung (``resume``: nach
        Prozessende, nach abgelegter Antwort des Boten) oder mit
        Entscheidung des Menschen (wartende Entscheidung, Pause). Eine
        Entscheidung ist eine Antwort, ein geänderter Auftrag ``task``
        (Bead neu gelesen) oder beides. Was zum Status nicht passt,
        weist die Lauf-Maschine ab."""
        self._load()
        if answer is not None and not answer.strip():
            raise RunResumeError("Antwort darf nicht leer sein")
        document = decision_document(
            _task(self._data),
            task or _task(self._data),
            answer,
            self._data["round_id"],
        )
        decided = answer is not None or changes_task(document)
        if not decided:
            self._refuse_without_decision()
            self._send_resume("resume", "Fortsetzen ohne Antwort")
            self._data["last_error"] = None
        elif answer is None and "answer" not in self._lauf.allowed:
            # Bead geändert, der Lauf wartet aber nicht auf den
            # Menschen (etwa nach Prozessende): fortsetzen, die
            # Änderung gilt ab dem nächsten Turn.
            self._send_resume("resume", "Fortsetzen")
            self._data["last_error"] = None
        else:
            self._send_resume("answer", "Eine Antwort")
            self._answer()
        if decided:
            self._decide(document, task)
        self._drive()
        return self.result()

    def _refuse_without_decision(self) -> None:
        """Ein Halt für den Menschen geht nur mit Entscheidung weiter;
        ohne sie stünde dieselbe Frage erneut an."""
        if "resume" not in self._lauf.allowed and (
            "answer" in self._lauf.allowed
        ):
            raise RunResumeError(
                "Der Lauf wartet auf eine Entscheidung: Auftrag im "
                "Bead ändern und/oder eine Antwort geben "
                "(resume --answer)"
            )

    def _send_resume(self, event: str, what: str) -> None:
        try:
            self._lauf.send(event)
        except TransitionNotAllowed:
            raise RunResumeError(
                f"{what} passt nicht zum Laufstatus "
                f"{self._lauf.status} (möglich: "
                f"{', '.join(self._lauf.allowed) or '-'})"
            ) from None

    def _answer(self) -> None:
        """Entscheidung des Menschen: nach einer Pause geht es im
        Quellzustand weiter, der Ablauf bewegt sich nicht; eine
        wartende Entscheidung setzt der Ablauf fort (zum Controller)."""
        run = decode_run_state(self._data["run_state"])
        if run.escalation is not None:
            update = {
                "run_state": encode_run_state(
                    replace(run, escalation=None)
                )
            }
        else:
            try:
                update = self._transition(run, ResumeRequested())
            except InvalidTransition as exc:
                raise RunResumeError(
                    f"Antwort passt nicht zu {run.state.phase.value}"
                ) from exc
        self._apply({**update, "decision": None, "last_error": None})

    def _decide(
        self, document: dict[str, object], task: RunTask | None
    ) -> None:
        """Entscheidung festhalten; ein geänderter Auftrag ersetzt die
        Kopie im Lauf, damit Prompts und Bindung von ``fix`` ihm
        folgen."""
        update: dict[str, object] = {
            "decisions": [*self._data["decisions"], document]
        }
        if task is not None and changes_task(document):
            update["task"] = _encode_task(task)
            update |= self._adopt_bead_change(task)
        self._apply(update)

    def _adopt_bead_change(self, task: RunTask) -> dict[str, object]:
        """Die Änderung des Menschen am Bead gehört nicht zum Ergebnis
        des Laufs: die Beads-Grenzen, die auf dem letzten erfassten
        Stand stehen, rücken auf den heutigen. Hat sich daneben ein
        anderer Bead geändert, bleibt der Lauf, wie er war."""
        state = self._data
        names = ("run_base", "round_base", "reviewed_refs")
        last = _last_checkpoint(state)
        if last is None:
            return {}
        issues = frozenset(
            source[3:]
            for source in task.sources
            if source.startswith("bd:")
        )
        try:
            moved = self.evidence_collector.adopt_issue_change(
                task, last, issues
            )
        except Exception as exc:
            raise RunResumeError(
                f"Entscheidung nicht übernommen: {exc}"
            ) from exc
        before = cast(dict[str, object], last).get("beads")
        beads = cast(dict[str, object], moved).get("beads")
        if beads == before:
            return {}
        update: dict[str, object] = {}
        for name in names:
            refs = cast("dict[str, object] | None", state[name])
            if refs is not None and refs["beads"] == before:
                update[name] = {**refs, "beads": beads}
        return update

    def reconcile(
        self, operation_id: str, artifact: object
    ) -> RunResult:
        """Uebernimm ein extern abgeglichenes Ergebnis explizit."""
        self._load()
        try:
            self._lauf.send("reconcile")
        except TransitionNotAllowed:
            raise RunResumeError(
                "Lauf hat keine unklare Operation"
            ) from None
        pending = cast(Operation, self._lauf.pending)
        if pending["id"] != operation_id:
            raise RunResumeError(
                "Abgleich gehoert nicht zur unklaren Operation"
            )
        if pending["call_id"]:
            try:
                self._ledger.reconcile(
                    cast(str, pending["call_id"]), artifact
                )
            except SafetyStop as exc:
                raise RunResumeError(str(exc)) from exc
        self.store.write_artifact(operation_id, artifact)
        self._data["last_error"] = None
        self._drive()
        return self.result()

    def result(self) -> RunResult:
        if self._data is None:
            self._load()
        return _result(self._lauf, self._data)

    def _load(self) -> None:
        self._lauf, self._data = _read_record(self.store)

    def _drive(self) -> None:
        """Schritte fahren, bis die Lauf-Maschine hält; nach jedem
        Schritt den Datensatz atomar ersetzen. Die Schrittgrenze folgt
        aus den Grenzen des Laufs (jede Rückkante zählt)."""
        run = decode_run_state(self._data["run_state"])
        maximum_steps = 20 + 12 * (
            run.limits.worker_attempts
            + run.limits.protocol_attempts
            + run.limits.process_retries
        )
        steps = 0
        while not self._lauf.halted:
            if steps == maximum_steps:
                raise RuntimeError(
                    f"Lauf {run.run_id} überschreitet die "
                    f"Schrittgrenze {maximum_steps}"
                )
            self._step()
            self._save()
            steps += 1

    def _save(self) -> None:
        """Erst die genommenen Kanten ins Ereignisprotokoll, dann den
        Datensatz: nach einem Absturz dazwischen schreibt die
        Wiederholung dieselben Zeilen nicht doppelt (``line``)."""
        run = decode_run_state(self._data["run_state"])
        for step in self._lauf.drain_steps():
            self._data["logged"] += 1
            self._log_step(run.run_id, step)
        self.store.save_record(encode_record(self._lauf, self._data))

    def _log_step(self, run_id: str, step: Step) -> None:
        transition = step.transition
        _log.info(
            "%s: %s --%s--> %s",
            step.region,
            transition.source,
            transition.event,
            transition.target,
        )
        ts = datetime.now(UTC).isoformat()
        line = self._data["logged"]
        self.store.append_event(
            event_record(
                line=line,
                seq=step.seq,
                ts=ts,
                flow=IMPLEMENT,
                run_id=run_id,
                transition=transition,
                target=transition.target,
                adapter=step.adapter,
            )
            if step.region == ABLAUF
            else run_event_record(
                line=line,
                seq=step.seq,
                ts=ts,
                run_id=run_id,
                region=step.region,
                transition=transition,
            )
        )

    def _apply(self, update: dict[str, object]) -> None:
        self._data.update(cast(RunData, update))

    def _step(self) -> None:
        """Einen Schritt fahren: eine offene Operation geht vor; sonst
        sagt der Ablauf, was zu tun ist (Moore-Ausgabe). Sofort
        erzeugte Ereignisse laufen direkt durch ``advance``, externe
        Wirkungen als Operation der Lauf-Maschine."""
        state = self._data
        pending = self._lauf.pending
        if pending is not None:
            self._apply(self._progress_operation(state, pending))
            return
        run = decode_run_state(state["run_state"])
        kind = operation(run.state, run.limits)
        if kind is None:
            raise RuntimeError(
                f"Ablauf hält in {run.state.phase.value}, der Lauf "
                "fährt aber"
            )
        if kind == "start":
            self._apply(self._transition(run, RunStarted()))
        elif kind == "task":
            self._apply(
                self._transition(run, ControllerTask(_task(state).task))
            )
        elif kind == "prepare":
            self._apply(self._prepare_worker(state, run))
        elif kind == "checkpoint":
            self._apply(self._transition(run, CheckpointRecorded()))
        else:
            self._lauf.send(
                "hold", operation=self._operation(state, run, kind)
            )

    def _prepare_worker(
        self, state: RunData, run: RunState
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
        self, state: RunData, run: RunState, kind: str
    ) -> Operation:
        """Offene Operation mit stabiler Kennung: eine Wiederholung
        derselben Wirkung trifft ihr gespeichertes Ergebnis wieder."""
        repeatable = cast(
            FlowOperation, operation_of(run.state, run.limits)
        ).repeatable
        if repeatable:
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
        return {
            "id": operation_id,
            "kind": kind,
            "repeatable": repeatable,
        }

    def _progress_operation(
        self, state: RunData, pending: Operation
    ) -> dict[str, object]:
        """Zwei-Schreib-Protokoll: ein gespeichertes Ergebnis gilt;
        sonst Absicht speichern, Wirkung ausführen, Ergebnis
        speichern. Eine Absicht ohne Ergebnis nach Prozessende ist
        unklar, außer die Operation ist wiederholbar."""
        operation_id = cast(str, pending["id"])
        stored = self.store.load_artifact(operation_id)
        if stored is not None:
            self._lauf.send("artifact_saved")
            return self._accept_artifact(state, pending, stored)
        if self._lauf.started:
            self._lauf.send("interrupted")
            if self._lauf.halted:
                return {
                    "last_error": (
                        "Externe Wirkung wurde begonnen, aber kein "
                        f"Ergebnis wurde gesichert: {operation_id}"
                    )
                }
        else:
            stopped = self._begin(state, pending)
            if stopped is not None:
                return stopped
        return self._effect(state, cast(Operation, self._lauf.pending))

    def _begin(
        self, state: RunData, pending: Operation
    ) -> dict[str, object] | None:
        """Schutzwächter und Budget vor dem Aufruf; dann die Absicht
        speichern. Ein Schutzhalt liefert sein Update."""
        call_id = None
        if pending["kind"] in _AGENT_ROLES:
            actor = self._actor(pending)
            blocker = self._call_guards(
                _AGENT_ROLES[cast(str, pending["kind"])], actor
            )
            if blocker is not None:
                return self._safety_stop(state, blocker)
            if Measure.BUDGET in actor.spec.measures:
                call_id = f"{pending['id']}-{uuid.uuid4().hex}"
                try:
                    self._reserve(state, pending, actor, call_id)
                except SafetyStop as exc:
                    return self._safety_stop(state, str(exc))
        self._lauf.send("start", call_id=call_id)
        self._save()
        return None

    def _effect(
        self, state: RunData, pending: Operation
    ) -> dict[str, object]:
        """Externe Wirkung außerhalb der Maschinen; ihr Ausgang wird
        Ereignis."""
        try:
            value = self._metered_operation(state, pending)
        except AnswerPending as exc:
            # Halt des Ausführers, kein Ablaufzustand: die Operation
            # bleibt offen und läuft nach der Antwort des Boten erneut.
            self._lauf.send("answer_pending")
            return {"last_error": str(exc)}
        except (AgentTurnError, SafetyStop, PermissionError) as exc:
            return self._safety_stop(state, str(exc))
        except AgentProtocolError as exc:
            return self._protocol_failure(state, str(exc))
        except Exception as exc:
            return self._process_failure(
                state, f"{type(exc).__name__}: {exc}"
            )
        self.store.write_artifact(cast(str, pending["id"]), value)
        self._lauf.send("artifact_saved")
        return self._accept_artifact(state, pending, value)

    def _reserve(
        self,
        state: RunData,
        pending: dict[str, object],
        actor: Worker | Reviewer,
        call_id: str,
    ) -> None:
        """Aufruf im Laufbudget buchen (deklarierte Messung
        ``budget``)."""
        self._ledger.reserve(
            call_id,
            cast(str, pending["id"]),
            True,
            actor.spec.transport,
            attribution=self._usage_attribution(state, pending, actor),
        )

    def _actor(self, pending: dict[str, object]) -> Worker | Reviewer:
        if pending["kind"] == "work":
            return self.worker
        return self.reviewer

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
        Selbsteinschaetzung des Agenten. Der Waechter gilt nur, wenn
        der Executor ``context`` deklariert (z. B. nicht Codex); dann
        ist die Messung Pflicht: ``UNAVAILABLE`` und ``UNSUPPORTED``
        sind Blocker, ein unbelegter Kontext gilt nicht als klein.

        Ein fehlendes Rollenbudget ist unabhaengig vom Kontextstatus
        keine gueltige Konfiguration: es steuert auch den nativen
        Timeout und die Verbrauchserfassung im Adapter (siehe
        ``CliAdapter.send_turn``/``claude_result``/``codex_result``).
        Ein fehlender Messwert darf das deshalb nicht stillschweigend
        uebertoenen; die Pruefung steht vor jeder Fallunterscheidung
        nach Kontextstatus.

        Eine Sitzung, die erst dieser Aufruf anlegt (``session_id``
        ``None``), hat noch keinen Kontext; zu messen gibt es nichts.
        """
        if Measure.CONTEXT not in actor.spec.measures:
            return None
        agent = _measured(actor)
        if agent.budget is None:
            raise ValueError(
                f"{role} (executor={actor.spec.name}, "
                f"session={agent.session_id}): TurnBudget fehlt; "
                "Timeout und Verbrauchserfassung waeren ungueltig"
            )
        if agent.session_id is None:
            return None
        measurement = agent.executor.measure_context(agent.session_id)
        origin = _origin(role, actor)
        if measurement.status is not ContextStatus.MEASURED:
            detail = measurement.detail or measurement.status.value
            return (
                f"Kontextmessung fuer {origin} fehlt: {detail}; "
                "kein Aufruf ohne Nachweis"
            )
        if measurement.tokens >= agent.budget.max_context_tokens:
            return (
                f"Kontextgrenze erreicht fuer {origin}: gemessen "
                f"{measurement.tokens} >= Grenze "
                f"{agent.budget.max_context_tokens} "
                f"(Quelle: {measurement.status.value})"
            )
        return None

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

        Der Waechter gilt nur, wenn der Executor ``quota`` deklariert.
        Dann gibt ausser einem tatsaechlichen Messwert nur ``PENDING``
        (noch kein Turn im Fenster) einen Aufruf frei: ``UNSUPPORTED``
        und ``UNAVAILABLE`` blockieren und werden als eigene, von
        "Budget erschoepft" klar unterschiedene Ursache gemeldet.

        ``self._ledger.limits()`` kann bei einem Altlauf ohne
        ``min_remaining_percent`` im Manifest ``SafetyStop`` werfen;
        anders als bei ``_ledger.reserve`` gibt es hier keinen
        umschliessenden ``try/except`` in ``_progress_operation``, die
        Ausnahme wird deshalb hier selbst in einen Blocker-Text
        uebersetzt statt unbehandelt aus dem Graph-Tick zu entkommen.
        """
        if Measure.QUOTA not in actor.spec.measures:
            return None
        agent = _measured(actor)
        try:
            limits = self._ledger.limits()
        except SafetyStop as exc:
            return str(exc)
        measurement = agent.executor.measure_quota(agent.session_id)
        origin = _origin(role, actor)
        if measurement.status is QuotaStatus.PENDING:
            return None
        if measurement.status is not QuotaStatus.MEASURED:
            return _quota_missing_reason(origin, measurement)
        reasons = [
            reason
            for reason in (
                _quota_reserve_reason(origin, measurement, limits),
                self._quota_delta_reason(
                    origin, measurement, role, agent.budget
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
            role=_AGENT_ROLES[pending["kind"]],
            purpose=purpose,
            session_id=getattr(actor, "session_id", None),
        )

    def _metered_operation(
        self, state: RunData, pending: dict[str, object]
    ) -> object:
        if pending["kind"] not in _AGENT_ROLES:
            return self._execute_operation(state, pending)
        actor = self._actor(pending)
        if Measure.BUDGET not in actor.spec.measures:
            # Ohne deklarierte Messung bucht ki-dev nichts (manual,
            # mock): die Sitzung des Boten misst ki-dev nicht.
            return self._execute_operation(state, pending)
        call_id = pending.get("call_id")
        if not call_id:
            raise SafetyStop(
                "Agentenaufruf ohne persistierte Budgetreservierung"
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
            if not isinstance(exc, AgentProtocolError):
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
        self, state: RunData, detail: str
    ) -> dict[str, object]:
        """Technischer Schutzhalt: Kante ``execution_stopped`` des
        Ablaufs, Fortsetzungspunkt ist der aktuelle Zustand."""
        self._lauf.send("failed")
        run = decode_run_state(state["run_state"])
        update = self._transition(run, ExecutionStopped(detail))
        return self._guard_halt(state, update, detail)

    def _guard_halt(
        self,
        state: RunData,
        update: dict[str, object],
        detail: str,
    ) -> dict[str, object]:
        """Hülle eines Halts mit Ursache ``execution_guard``."""
        return self._write_handoff_if_stopped(
            state, {**update, "last_error": detail}, detail
        )

    def _write_handoff_if_stopped(
        self,
        state: RunData,
        update: dict[str, object],
        reason: str,
    ) -> dict[str, object]:
        """Persistiere die kompakte Sitzungsuebergabe fuer jeden Halt.

        Gilt fuer jede Eskalation (Pause des Laufs) und jeden
        wartenden Ablaufzustand -- unabhaengig davon, ob eine
        Maschinengrenze, ein Prozessfehler oder ein Reviewer-Urteil
        (``ESCALATE``/``NEEDS_DECISION``) den Halt ausgeloest hat.
        """
        next_run = decode_run_state(
            cast(dict[str, object], update["run_state"])
        )
        if (
            next_run.escalation is None
            and next_run.state.phase not in WAITING_PHASES
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
        self, state: RunData, pending: dict[str, object]
    ) -> object:
        data = {
            **state,
            "task": _task(state),
            "operation_id": pending["id"],
            "attempt_id": _review_attempt(state, pending),
        }
        return self._operations.execute(
            cast(str, pending["kind"]), data
        )

    def _accept_artifact(
        self,
        state: RunData,
        pending: Operation,
        artifact: object,
    ) -> dict[str, object]:
        name = cast(str, pending["kind"])
        update, event_name = self._operations.accept(name, artifact)
        binding = IMPLEMENT.bindings[name]
        if binding.success is not None:
            payload = project(artifact, binding.payload or {})
            event = decode_operation_event(event_name, payload)
            run = decode_run_state(state["run_state"])
            moved = self._transition(run, event)
            detail = artifact.get("detail")
            return self._write_handoff_if_stopped(
                state,
                {**moved, **update, "last_error": detail},
                detail or "Operation abgeschlossen",
            )
        run = decode_run_state(state["run_state"])
        decision_doc = cast(dict[str, object], artifact["decision"])
        decision = _decode_decision(decision_doc)
        self.store.write_message(cast(str, pending["id"]), decision_doc)
        update = self._apply_decision(state, run, decision)
        return {
            **update,
            "decision": decision_doc,
            "review_sequence": state["review_sequence"] + 1,
        }

    def _apply_decision(
        self,
        state: RunData,
        run: RunState,
        decision: ReviewDecision,
    ) -> dict[str, object]:
        verdict = IMPLEMENT.verdict(decision.event)
        if verdict is Verdict.CHANGES:
            facts, guard_detail = self._changes_facts(run, decision)
            update = self._transition(
                run, ControllerChanges(decision.detail), facts=facts
            )
            if _halted_by_guard(update):
                return self._guard_halt(state, update, guard_detail)
            next_run = decode_run_state(
                cast(dict[str, object], update["run_state"])
            )
            if next_run.halted:
                return self._write_handoff_if_stopped(
                    state, update, decision.detail
                )
            return {
                **update,
                "round_id": state["round_id"] + 1,
                "open_objection": decision.detail,
                "round_base": None,
                "work_report": None,
                "evidence": None,
            }
        if verdict is Verdict.PASS:
            return self._pass(state, run)
        if verdict is Verdict.NEEDS_DECISION:
            return self._write_handoff_if_stopped(
                state,
                self._transition(
                    run, ControllerNeedsDecision(decision.detail)
                ),
                decision.detail,
            )
        return self._write_handoff_if_stopped(
            state,
            self._transition(run, ControllerEscalate(decision.detail)),
            decision.detail,
        )

    def _pass(self, state: RunData, run: RunState) -> dict[str, object]:
        """PASS mit dem Fakt ``checks_failed`` für das Test-Tor von
        ``implement.toml``: rote Prüfungen der Runde halten den Lauf
        für den Menschen an, statt zu integrieren."""
        failed = failed_checks(state["evidence"])
        if not failed:
            return self._transition(run, ControllerPass())
        update = self._transition(
            run, ControllerPass(), facts=frozenset({"checks_failed"})
        )
        detail = (
            f"Review PASS bei roter Prüfung: {', '.join(failed)}. "
            "Ein Mensch entscheidet: Bead ändern und/oder "
            "resume --answer."
        )
        return self._write_handoff_if_stopped(
            state, {**update, "last_error": detail}, detail
        )

    def _changes_facts(
        self, run: RunState, decision: ReviewDecision
    ) -> tuple[frozenset[str], str]:
        """Fakten aus Laufdaten außerhalb des Maschinenzustands
        (Verbrauchsbuch, Beanstandungsverlauf) für die Wächter
        ``changes_refused`` und ``stagnation`` von
        ``implement.toml``.

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
            verdict=IMPLEMENT.verdict(decision.event),
            requirement_ref=decision.requirement_ref,
            limit=limits.max_stagnant_changes,
        )
        if reason is not None:
            return frozenset({"stagnation"}), reason
        return frozenset(), decision.detail

    def _protocol_failure(
        self, state: RunData, detail: str
    ) -> dict[str, object]:
        self._lauf.send("failed")
        run = decode_run_state(state["run_state"])
        update = self._transition(run, ProtocolError(detail))
        return self._write_handoff_if_stopped(
            state, {**update, "last_error": detail}, detail
        )

    def _process_failure(
        self, state: RunData, detail: str
    ) -> dict[str, object]:
        self._lauf.send("failed")
        run = decode_run_state(state["run_state"])
        # Welches Ereignis das Scheitern ist, sagt die Operation des
        # Ablaufs (`failure`), nicht der Ausführer.
        failed = operation_of(run.state, run.limits)
        if failed is None or failed.failure is None:
            raise RuntimeError(
                f"Operation in {run.state.phase.value} ohne failure "
                f"scheiterte: {detail}"
            )
        event = EVENT_TYPES[failed.failure](detail)
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
                "round_base": None if prepares else state["round_base"],
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
        """Ablauf fortschreiben, über die eine Maschine des Laufs: was
        das im Lauf auslöst (Pause bei Eskalation, Warten, Ende), nimmt
        die Bibliothek mit."""
        result = self._lauf.advance(
            run, event, facts=facts, adapter=self._adapter_of(run)
        )
        return self._replace_run(run, result.state, result.escalation)

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


def _review_attempt(state: RunData, pending: dict[str, object]) -> str:
    """Review-Operation plus Protokollversuch: eine Wiederholung nach
    ungültiger Antwort ist ein neuer Versuch."""
    counters = decode_run_state(state["run_state"]).state.counters
    return f"{pending['id']}-t{counters.protocol_attempt:04d}"


def _adapter_name(actor: Worker | Reviewer) -> str:
    return actor.spec.name


def _measured(actor: Worker | Reviewer) -> AgentWorker | AgentReviewer:
    """Rolle mit deklarierter Messung: die Deklaration ist beim Laden
    gegen die Fähigkeiten des Transports geprüft (``registry``)."""
    return cast(AgentWorker | AgentReviewer, actor)


def _origin(role: str, actor: Worker | Reviewer) -> str:
    session = getattr(actor, "session_id", None) or "neu"
    return f"{role} (executor={actor.spec.name}, session={session})"


def _halted_by_guard(update: dict[str, object]) -> bool:
    run = decode_run_state(cast(dict[str, object], update["run_state"]))
    return (
        isinstance(run.escalation, MachineEscalation)
        and run.escalation.cause
        is MachineEscalationCause.EXECUTION_GUARD
    )


def _result(lauf: RunMachine, data: RunData) -> RunResult:
    run = decode_run_state(data["run_state"])
    pending = lauf.pending or {}
    detail = data["last_error"]
    if run.escalation is not None:
        cause = str(run.escalation.cause)
        detail = f"{cause}: {detail}" if detail else cause
    return RunResult(
        run_id=run.run_id,
        status=lauf.status,
        round_id=data["round_id"],
        phase=run.state.phase,
        detail=detail,
        operation_id=cast(str | None, pending.get("id")),
    )


def read_run_status(store: RunStore) -> RunResult:
    """Lies den zuletzt gespeicherten Laufstatus rein lesend.

    Der Datensatz wird je Schritt atomar ersetzt (``os.replace``); ein
    Leser sieht deshalb immer einen ganzen Stand, nie eine Mischung aus
    zwei Schreibvorgängen. Ein ungültiger Datensatz wird als
    ``RunResumeError`` mit Feldpfad gemeldet."""
    return _result(*_read_record(store))


def _read_record(store: RunStore) -> tuple[RunMachine, RunData]:
    try:
        document = store.load_record()
    except RunStoreError as exc:
        raise RunResumeError(
            f"Lauf {store.run_id} ist unvollstaendig: {exc}"
        ) from exc
    if document is None:
        if (store.run_dir / _LANGGRAPH_CHECKPOINT).exists():
            raise RunResumeError(
                f"Lauf {store.run_id} stammt aus einer älteren "
                "ki-dev-Version (LangGraph-Checkpoint) und ist nicht "
                "fortsetzbar; bitte neu starten"
            )
        raise RunResumeError(f"Lauf {store.run_id} fehlt")
    try:
        return decode_record(document)
    except (RunRecordError, RecordError, RunStateFormatError) as exc:
        raise RunResumeError(
            f"Lauf {store.run_id} ist unvollstaendig: {exc}"
        ) from exc


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


def _last_checkpoint(state: RunData) -> object | None:
    """Zuletzt erfasste Grenze: Ergebnis der Runde, sonst ihre Basis,
    sonst das Ergebnis der vorigen Runde oder die Basis des Laufs."""
    if state["evidence"] is not None:
        return state["reviewed_refs"]
    for name in ("round_base", "reviewed_refs", "run_base"):
        if state[name] is not None:
            return state[name]
    return None


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


def _task(state: RunData) -> RunTask:
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


def _decode_decision(value: dict[str, object]) -> ReviewDecision:
    return ReviewDecision(
        cast(str, value["run_id"]),
        cast(int, value["round_id"]),
        cast(str, value["event"]),
        cast(str, value["detail"]),
        cast("str | None", value["requirement_ref"]),
    )


@dataclass(frozen=True)
class StaticEvidenceCollector:
    """Einfacher Collector fuer kontrollierte Einbettungen und Tests."""

    contexts: tuple[ControllerContext, ...]

    def prepare(self, task: RunTask, round_id: int) -> object:
        return {"run_id": task.run_id, "round_id": round_id}

    def adopt_issue_change(
        self, task: RunTask, refs: object, issues: frozenset[str]
    ) -> object:
        del task, issues
        return refs

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
