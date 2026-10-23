"""Gemeinsame Implementierungsoperationen mit expliziten Eingaben.

Promptbau, Nachweise und Antwortdeutung gehören zu diesen Diensten.
Der Ausführer injiziert Ressourcen; das Paket bindet die Daten.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import cast

from ki_dev.adapter.contract import (
    ReviewRequest,
    RunTask,
    WorkReport,
    WorkRequest,
)
from ki_dev.deltas import (
    ControllerContext,
    StepDeltaAssessment,
    assess_step_delta,
)
from ki_dev.flow.binding import OperationSpec
from ki_dev.flow_ops.implement.machine import EVENT_TYPES, IMPLEMENT
from ki_dev.flow_ops.implement.review_output import (
    REVIEW_VOCABULARY,
    ReviewDecision,
    bind_review_decision,
    parse_review_decision,
)
from ki_dev.flow_ops.implement.turns import review_prompt, work_prompt
from ki_dev.review_context import project_review_context
from ki_dev.runner.review_output import (
    AgentProtocolError,
)


@dataclass
class ImplementationOperations:
    worker: object
    reviewer: object
    evidence_collector: object
    finalizer: object
    limits: object

    def catalog(self) -> dict[str, OperationSpec]:
        return {
            "agent.work": OperationSpec(
                self.work,
                {"type": "array", "minItems": 5, "maxItems": 5},
                {"type": "object"},
            ),
            "evidence.collect": OperationSpec(
                self.evidence,
                {"type": "array", "minItems": 5, "maxItems": 5},
                {
                    "type": "object",
                    "required": ["context", "projection", "assessment"],
                },
                _evidence_output,
            ),
            "review.decide": OperationSpec(
                self.review,
                {"type": "array", "minItems": 6, "maxItems": 6},
                {"type": "object", "required": ["decision", "raw"]},
                _review_output,
            ),
            "git.freeze": OperationSpec(
                self.freeze,
                {"type": "array", "minItems": 3, "maxItems": 3},
                {"type": "object"},
            ),
            "git.finalize_history": OperationSpec(
                self.finalize_history,
                {"type": "array", "minItems": 1, "maxItems": 1},
                {"type": "object"},
            ),
            "git.verify": OperationSpec(
                self.verify_final,
                {"type": "array", "minItems": 2, "maxItems": 2},
                {"type": "object"},
            ),
            "git.integrate": OperationSpec(
                self.integrate,
                {"type": "array", "minItems": 2, "maxItems": 2},
                {"type": "object"},
            ),
        }

    def work(
        self, task, round_id, open_objection, decisions, operation_id
    ) -> object:
        report = self.worker.work(
            WorkRequest(
                task,
                round_id,
                work_prompt(task, round_id, open_objection, decisions),
                operation_id,
            )
        )
        return {"summary": report.summary}

    def evidence(
        self, task, round_id, work_report, round_base, run_base
    ) -> object:
        report = WorkReport(cast(str, work_report))
        context = self.evidence_collector.collect(
            task,
            round_id,
            round_base,
            run_base,
            report,
        )
        _validate_context(context, task, round_id)
        projection = project_review_context(context, limits=self.limits)
        return {
            "context": _context_document(context),
            "projection": {
                "text": projection.text,
                "omissions": [
                    asdict(omission)
                    for omission in projection.omissions
                ],
            },
            "assessment": assess_step_delta(context.step_delta).value,
        }

    def review(
        self,
        task,
        round_id,
        evidence,
        work_report,
        decisions,
        attempt_id,
    ) -> object:
        evidence = cast(dict[str, object], evidence)
        summary = cast(str, work_report)
        from ki_dev.review_context import Omission, ReviewProjection

        omissions = cast(list[dict[str, str]], evidence["omissions"])

        projection = ReviewProjection(
            text=cast(str, evidence["text"]),
            omissions=tuple(Omission(**item) for item in omissions),
        )
        raw = self.reviewer.review(
            ReviewRequest(
                task,
                round_id,
                review_prompt(
                    task,
                    round_id,
                    summary,
                    projection,
                    REVIEW_VOCABULARY,
                    decisions,
                ),
                REVIEW_VOCABULARY,
                attempt_id,
            )
        )
        decision = parse_review_decision(
            raw, run_id=task.run_id, round_id=round_id
        )
        decision = bind_review_decision(decision, task)
        return {
            "raw": raw,
            "decision": _decision_document(decision),
            "decisions": decisions,
        }

    def freeze(self, task, run_base, reviewed_refs) -> object:
        base_refs = cast(dict[str, object], run_base)
        reviewed_refs = cast(dict[str, object], reviewed_refs)
        return self.finalizer.freeze(
            source=task.workdir,
            run_id=task.run_id,
            base_refs=base_refs,
            reviewed_refs=reviewed_refs,
        )

    def finalize_history(self, frozen_result) -> object:
        return self.finalizer.finalize_history(
            cast(dict[str, object], frozen_result)
        )

    def verify_final(self, frozen_result, final_result) -> object:
        return self.finalizer.verify(
            cast(dict[str, object], frozen_result),
            cast(dict[str, object], final_result),
        )

    def integrate(self, frozen_result, final_result) -> object:
        return self.finalizer.integrate(
            cast(dict[str, object], frozen_result),
            cast(dict[str, object], final_result),
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


def _decision_document(decision: ReviewDecision) -> dict[str, object]:
    return {
        "run_id": decision.run_id,
        "round_id": decision.round_id,
        "event": decision.event,
        "verdict": IMPLEMENT.verdict(decision.event).value,
        "detail": decision.detail,
        "requirement_ref": decision.requirement_ref,
    }


def _result_refs(context: dict) -> dict:
    step = context["step_delta"]
    return {
        medium: step[medium]["boundary"]["result"]
        for medium in ("git", "beads")
    }


def decode_operation_event(name: str, payload: dict):
    """Typisierte Ereignisnutzlast des Implementierungsvertrags."""
    if "assessment" in payload:
        payload = {
            **payload,
            "assessment": StepDeltaAssessment(payload["assessment"]),
        }
    return EVENT_TYPES[name](**payload)


def _evidence_output(artifact: dict) -> dict:
    """``failed_checks`` reist mit der Projektion in ``evidence``: das
    Review liest die Prüfungen als Text, das Test-Tor des Ablaufs
    entscheidet über ihre Namen (:func:`failed_checks`)."""
    context = artifact["context"]
    return {
        **artifact,
        "projection": {
            **artifact["projection"],
            "failed_checks": [
                check["name"]
                for check in context["checks"]
                if not check["passed"]
            ],
        },
        "reviewed_refs": _result_refs(context),
    }


def failed_checks(evidence: object) -> tuple[str, ...]:
    """Rote Prüfungen der Runde aus ``evidence`` der Laufdaten; ein
    Lauf aus der Zeit vor dem Test-Tor nennt keine."""
    if not isinstance(evidence, dict):
        return ()
    return tuple(cast(list[str], evidence.get("failed_checks", [])))


def _review_output(artifact: dict) -> dict:
    return {**artifact, "event": artifact["decision"]["event"]}
