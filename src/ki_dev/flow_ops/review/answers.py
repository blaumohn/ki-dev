"""Antwortdeutung des Review-Musters für jeden Executor.

Deutung der Antworten je Zustandsart, Vorlauf als Katalogoperation
und die Eingaben der Übergaben (Bericht, Befund, Urteil,
Prüfsteuerung, Rückmeldung) aus den Laufdaten; gleich für den
Menschen als Boten (manual) wie für einen Agenten. Die Deutung
gleicht nichts mit dem Stand des Repos ab: wer antwortet,
verantwortet, was er mitgibt.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from functools import partial
from pathlib import Path
from typing import ClassVar, cast

from jsonschema import Draft202012Validator

from ki_dev.flow.binding import OperationSpec
from ki_dev.flow.model import Transition
from ki_dev.flow.review_flow import ReviewFlow
from ki_dev.flow_ops.review.model import (
    FACTS,
    FULL_CHECKS,
    ReviewModel,
)
from ki_dev.ops.checks import PREFLIGHT
from ki_dev.ops.checks.options import (
    CONTROL_SCHEMA,
    check_control,
    control_from,
)
from ki_dev.ops.checks.preflight import report_data, report_of
from ki_dev.ops.checks.run import run_checks
from ki_dev.ops.context.bead_input import BeadInput, criteria_with_refs
from ki_dev.ops.context.blocks import TurnInput
from ki_dev.review_decision import ReviewVerdict
from ki_dev.runner.package import Handoff
from ki_dev.runner.review_output import (
    AgentProtocolError,
    PlanningAnswer,
    parse_planning_answer,
)
from ki_dev.step.boundary import (
    feedback_limit,
    progress,
    project_preflight_config,
)
from ki_dev.step.package import AnswerError, Call

REVIEW_KIND = "review"
MACHINE_KIND = "machine"
WRITE_KINDS = ("write", "correction")

DONE = "done"
"""Ereignis „Schreiben bzw. Korrektur getan“: die Antwort des Boten
auf eine Schreib- oder Korrekturübergabe."""

COUNT = {"type": "integer", "minimum": 1}
FLOW_LIMITS = {
    "changes_rounds": 5,
    "worker_attempts": 12,
    "max_failed_corrections": 2,
    "max_stagnant_changes": 3,
}
"""Standardwerte der Ablaufgrenzen (``limits.flow``): Runden der
Änderungen, Versuche des Schreibens, abgelehnte Korrekturen und
Änderungen ohne Fortschritt."""
FLOW_LIMITS_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": list(FLOW_LIMITS),
    "properties": dict.fromkeys(FLOW_LIMITS, COUNT),
}

# Laufdaten des Musters neben denen der Wächter (model.py).
REPORT = "report"
FINDING = "finding"
VERDICT = "verdict"
CONTROL = "control"
FEEDBACK = "feedback"


@dataclass(frozen=True)
class ReviewOps:
    """Ops des Review-Musters für step
    (:class:`~ki_dev.step.package.PackageOps`)."""

    flow: ReviewFlow
    model: type[ReviewModel] = ReviewModel
    flow_limits: ClassVar[Mapping[str, object]] = FLOW_LIMITS
    flow_limits_schema: ClassVar[Mapping[str, object]] = (
        FLOW_LIMITS_SCHEMA
    )

    def catalog(self, call: Call) -> Mapping[str, OperationSpec]:
        return {
            PREFLIGHT: OperationSpec(
                partial(_checks, call),
                {"type": "array"},
                {"type": "object"},
            )
        }

    def read(
        self, call: Call, handoff: Handoff, raw: str
    ) -> tuple[dict, str]:
        """Schreiben und Korrektur enden mit ``done`` (optional mit
        Rückmeldung), das Review mit einem geprüften Urteil,
        Entscheidung und Quelle mit einem ihrer Ereignisse."""
        kind = self._kind(handoff.state)
        if kind in WRITE_KINDS:
            return _done(raw), DONE
        if kind == REVIEW_KIND:
            return self._verdict(raw, call.issue)
        return {}, self._chosen(handoff.state, raw)

    def subject(
        self,
        base: TurnInput,
        data: Mapping[str, object],
        path: Sequence[Transition],
    ) -> TurnInput:
        """Bericht, Befund, Urteil, Prüfsteuerung und Rückmeldung aus
        den Laufdaten; nahm eine Review-Antwort in diesem Aufruf eine
        Kante, nennen die Folgeschritte die ihres Urteils."""
        report = data.get(REPORT)
        finding = cast(str | None, data.get(FINDING))
        verdict = data.get(VERDICT)
        control = cast(Mapping[str, dict], data.get(CONTROL) or {})
        subject = replace(
            base,
            report=None if report is None else report_of(report),
            finding=finding,
            feedback=cast(str | None, data.get(FEEDBACK)),
            feedback_limit=(
                None if finding is None else feedback_limit()
            ),
            pass_allowed=self._pass_allowed(data),
            verdict=(
                None
                if verdict is None
                else ReviewVerdict(**cast(dict, verdict))
            ),
            preflight_args=control.get("args", {}),
            preflight_skip=control.get("skip", {}),
        )
        answered = self._answered(path)
        if answered is None:
            return subject
        return replace(
            subject, state=answered.source, events=(answered.event,)
        )

    def review(self, state: str) -> bool:
        return self._kind(state) == REVIEW_KIND

    def _kind(self, state: str) -> str:
        return self.flow.flow.state(state).kind

    def _verdict(self, raw: str, issue: BeadInput) -> tuple[dict, str]:
        """Urteil und vorgeschlagene Prüfsteuerung."""
        answer = self._parse(raw, issue)
        verdict = answer.verdict
        update = {
            VERDICT: {
                "event": verdict.event,
                "detail": verdict.detail,
                "requirement_ref": verdict.requirement_ref,
            },
            CONTROL: dict(
                zip(
                    ("args", "skip"),
                    control_from(answer.extras),
                    strict=True,
                )
            ),
        }
        return update, verdict.event

    def _parse(self, raw: str, issue: BeadInput) -> PlanningAnswer:
        """Antwort prüfen und an die Abnahmekriterien binden; die
        Steuerfelder prüft die Operation ``checks``."""
        refs = [ref for ref, _ in criteria_with_refs(issue)]
        try:
            return parse_planning_answer(
                raw,
                self.flow.flow,
                refs,
                CONTROL_SCHEMA,
                partial(
                    check_control, load_config=project_preflight_config
                ),
            )
        except AgentProtocolError as exc:
            raise AnswerError(
                f"Review-Antwort ungültig: {exc}"
            ) from exc

    def _chosen(self, state: str, raw: str) -> str:
        """Entscheidung des Menschen: ``{"event": …}`` mit einem
        Ereignis, das aus ``state`` führt."""
        events = sorted({t.event for t in self.flow.outgoing(state)})
        schema = {
            "type": "object",
            "required": ["event"],
            "additionalProperties": False,
            "properties": {"event": {"enum": events}},
        }
        value = _json(raw, schema, f"Antwort in {state}")
        return str(value["event"])

    def _answered(
        self, path: Sequence[Transition]
    ) -> Transition | None:
        """Die Kante, die eine Review-Antwort in diesem Aufruf nahm,
        wenn sie nicht in den Vorlauf führte."""
        if not path:
            return None
        entry = path[0]
        if self._kind(entry.source) != REVIEW_KIND:
            return None
        if self._kind(entry.target) == MACHINE_KIND:
            return None
        return entry

    def _pass_allowed(self, data: Mapping[str, object]) -> bool:
        """Ob das Review PASS zulassen kann (kein Teillauf)."""
        if not self.flow.binds(PREFLIGHT):
            return True
        return ReviewModel(None, dict(data)).full_checks()


def _done(raw: str) -> dict:
    """Antwort auf Schreiben oder Korrektur: ``{}`` oder
    ``{"feedback": …}``, die Rückmeldung an die nächste Übergabe
    (höchstens ``feedback_max_chars`` Zeichen, nie gekürzt)."""
    limit = feedback_limit()
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            FEEDBACK: {
                "type": "string",
                "pattern": r"\S",
                "maxLength": limit,
            }
        },
    }
    value = _json(raw, schema, "Antwort (done)")
    return {FEEDBACK: value[FEEDBACK]} if FEEDBACK in value else {}


def _json(raw: str, schema: dict, what: str) -> dict:
    """JSON-Objekt nach ``schema``; Diagnose nennt Feld und Regel, nie
    den Rohwert."""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AnswerError(f"{what}: kein JSON ({exc.msg})") from exc
    for error in Draft202012Validator(schema).iter_errors(value):
        path = ".".join(map(str, error.absolute_path)) or "$"
        raise AnswerError(f"{what} ungültig: {path}: {error.validator}")
    return cast(dict, value)


def _checks(call: Call) -> dict[str, object]:
    """Vorlauf dieses Projekts mit den Optionen des Aufrufs."""
    request = call.preflight
    outcome = run_checks(
        Path.cwd(), request.extra, request.skip, progress
    )
    partial_run = outcome.report is not None and outcome.report.partial
    return {
        "event": outcome.event,
        FACTS: [] if partial_run else [FULL_CHECKS],
        REPORT: (
            None
            if outcome.report is None
            else report_data(outcome.report)
        ),
        FINDING: outcome.failure,
    }
