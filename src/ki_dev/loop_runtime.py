"""Persistente LangGraph-Huelle fuer den begrenzten Bau--Review-Loop."""

from __future__ import annotations

import json
import sqlite3
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
from ki_dev.loop import (
    AgentBuildMode,
    AgentReviewer,
    BuildMode,
    BuildReport,
    BuildRequest,
    LoopProtocolError,
    LoopTask,
    ReviewAction,
    ReviewDecision,
    Reviewer,
    ReviewRequest,
    parse_review_decision,
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
from ki_dev.review_context import (
    DEFAULT_PROJECTION_LIMITS,
    ProjectionLimits,
    project_review_context,
)
from ki_dev.run_store import RunStore
from ki_dev.repository_finalization import Finalizer


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
        run = decode_run_state(state["run_state"])
        pending = state.get("pending_operation") or {}
        operation_id = cast(str | None, pending.get("id"))
        detail = state.get("last_error")
        if run.escalation is not None:
            cause = str(run.escalation.cause)
            detail = f"{cause}: {detail}" if detail else cause
        return LoopRunResult(
            run_id=run.run_id,
            status=state["status"],
            round_id=state["round_id"],
            phase=run.state.phase,
            detail=detail,
            operation_id=operation_id,
        )

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
        return {"configurable": {"thread_id": self.store.run_id}}

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
                "pending_operation": self._operation(state, "verify_final")
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
        attempt = (
            state["review_sequence"]
            if kind == "review"
            else run.state.counters.process_retry
        )
        if kind in {"freeze", "finalize_history", "verify_final", "integrate"}:
            operation_id = f"final-{kind}-r{run.revision:04d}"
        else:
            operation_id = f"r{state['round_id']:04d}-{kind}-a{attempt:04d}"
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
            started = {
                **pending,
                "status": "started",
                "invocation": self._invocation_id,
            }
            return {"pending_operation": started}
        if (
            pending.get("invocation") != self._invocation_id
            and pending.get("kind")
            not in {"freeze", "finalize_history", "verify_final", "integrate"}
        ):
            return {
                "status": "uncertain",
                "last_error": (
                    "Externe Wirkung wurde begonnen, aber kein "
                    "Ergebnis wurde "
                    f"gesichert: {operation_id}"
                ),
            }
        try:
            value = self._execute_operation(state, pending)
        except LoopProtocolError as exc:
            return self._protocol_failure(state, str(exc))
        except Exception as exc:
            return self._process_failure(
                state, f"{type(exc).__name__}: {exc}"
            )
        self.store.write_artifact(operation_id, value)
        return self._accept_artifact(state, pending, value)

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
            return {
                **update,
                "pending_operation": None,
                "status": "paused_interactive"
                if next_run.state.phase is Phase.PAUSED_INTERACTIVE
                else "running",
                "last_error": cast(str | None, artifact.get("detail")),
            }
        if kind == "integrate":
            ok = artifact.get("ok") is True
            update = self._transition(run, IntegrationCompleted(ok))
            next_run = decode_run_state(
                cast(dict[str, object], update["run_state"])
            )
            return {
                **update,
                "pending_operation": None,
                "status": "passed"
                if next_run.state.phase is Phase.PASSED
                else "paused_interactive",
                "last_error": None
                if ok
                else cast(str | None, artifact.get("detail")),
            }
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
            update = self._transition(
                run, ControllerChanges(decision.detail)
            )
            next_run = decode_run_state(
                cast(dict[str, object], update["run_state"])
            )
            if next_run.state.phase is Phase.PAUSED_INTERACTIVE:
                return {**update, "status": "paused_interactive"}
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
            return {
                **self._transition(
                    run, ControllerNeedsDecision(decision.detail)
                ),
                "interrupt_payload": {
                    "kind": "needs_decision",
                    "run_id": run.run_id,
                    "round_id": state["round_id"],
                    "question": decision.detail,
                },
            }
        return {
            **self._transition(
                run, ControllerEscalate(decision.detail)
            ),
            "interrupt_payload": {
                "kind": "escalate",
                "run_id": run.run_id,
                "round_id": state["round_id"],
                "reason": decision.detail,
            },
        }

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
        return {
            **update,
            "pending_operation": None,
            "status": status,
            "last_error": detail,
        }

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
        return {
            **update,
            "pending_operation": None,
            "round_base": None
            if next_run.state.phase is Phase.WORKER_STEP_PREPARE
            else state["round_base"],
            "status": "paused_interactive" if paused else "running",
            "last_error": detail,
        }

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


def _encode_task(task: LoopTask) -> dict[str, object]:
    return {
        "run_id": task.run_id,
        "task": task.task,
        "sources": list(task.sources),
        "workdir": str(task.workdir),
        "access_profile": task.access_profile,
    }


def _task(state: LoopGraphState) -> LoopTask:
    value = state["task"]
    return LoopTask(
        run_id=cast(str, value["run_id"]),
        task=cast(str, value["task"]),
        sources=tuple(cast(list[str], value["sources"])),
        workdir=Path(cast(str, value["workdir"])),
        access_profile=cast(str, value["access_profile"]),
    )


def _decision_document(decision: ReviewDecision) -> dict[str, object]:
    return {
        "run_id": decision.run_id,
        "round_id": decision.round_id,
        "action": decision.action.value,
        "detail": decision.detail,
    }


def _decode_decision(value: dict[str, object]) -> ReviewDecision:
    return ReviewDecision(
        cast(str, value["run_id"]),
        cast(int, value["round_id"]),
        ReviewAction(cast(str, value["action"])),
        cast(str, value["detail"]),
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
    """Extrahiere genau die Referenzen des dem Reviewer gezeigten Deltas."""
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
