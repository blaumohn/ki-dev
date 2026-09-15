"""Ein einzelner, austauschbarer Bau--Review-Zyklus."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from ki_dev.deltas import ControllerContext
from ki_dev.executors import Effort, Executor, TurnRequest
from ki_dev.review_context import (
    DEFAULT_PROJECTION_LIMITS,
    ProjectionLimits,
    ReviewProjection,
    project_review_context,
)


class ReviewAction(StrEnum):
    CHANGES = "CHANGES"
    PASS = "PASS"
    NEEDS_DECISION = "NEEDS_DECISION"
    ESCALATE = "ESCALATE"


class LoopProtocolError(ValueError):
    """Agentenausgabe verletzt Huelle oder Referenzbindung."""


@dataclass(frozen=True)
class LoopTask:
    run_id: str
    task: str
    sources: tuple[str, ...]
    workdir: Path
    access_profile: str

    def __post_init__(self) -> None:
        for name, value in (
            ("run_id", self.run_id),
            ("task", self.task),
            ("access_profile", self.access_profile),
        ):
            if not value.strip():
                raise ValueError(
                    f"LoopTask.{name} darf nicht leer sein"
                )
        if not self.workdir.is_absolute():
            raise ValueError("LoopTask.workdir muss absolut sein")
        if not isinstance(self.sources, tuple) or any(
            not isinstance(source, str) or not source.strip()
            for source in self.sources
        ):
            raise TypeError(
                "LoopTask.sources muss ein Tupel nichtleerer Texte sein"
            )


@dataclass(frozen=True)
class BuildRequest:
    task: LoopTask
    round_id: int
    objection: str | None = None


@dataclass(frozen=True)
class BuildReport:
    summary: str

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("BuildReport.summary darf nicht leer sein")


@dataclass(frozen=True)
class ReviewRequest:
    task: LoopTask
    round_id: int
    build_report: BuildReport
    evidence: ReviewProjection


@dataclass(frozen=True)
class ReviewDecision:
    run_id: str
    round_id: int
    action: ReviewAction
    detail: str = ""


class BuildMode(Protocol):
    def build(self, request: BuildRequest) -> BuildReport: ...


class Reviewer(Protocol):
    def review(self, request: ReviewRequest) -> str: ...


@dataclass
class AgentBuildMode:
    executor: Executor
    session_id: str
    model: str
    effort: Effort

    def build(self, request: BuildRequest) -> BuildReport:
        result = self.executor.send_turn(
            TurnRequest(
                session_id=self.session_id,
                model=self.model,
                effort=self.effort,
                message=_build_prompt(request),
            )
        )
        if not result.ok:
            raise RuntimeError(
                result.error
                or f"Bau-Turn fehlgeschlagen: {result.status}"
            )
        return BuildReport(result.stdout)


@dataclass
class AgentReviewer:
    executor: Executor
    session_id: str
    model: str
    effort: Effort

    def review(self, request: ReviewRequest) -> str:
        result = self.executor.send_turn(
            TurnRequest(
                session_id=self.session_id,
                model=self.model,
                effort=self.effort,
                message=_review_prompt(request),
            )
        )
        if not result.ok:
            raise RuntimeError(
                result.error
                or f"Review-Turn fehlgeschlagen: {result.status}"
            )
        return result.stdout


def run_review_round(
    *,
    task: LoopTask,
    round_id: int,
    build_mode: BuildMode,
    reviewer: Reviewer,
    context_after_build: Callable[[], ControllerContext],
    objection: str | None = None,
    limits: ProjectionLimits = DEFAULT_PROJECTION_LIMITS,
) -> ReviewDecision:
    """Fuehre einen Bau-Turn und danach einen gebundenen Review aus."""
    if round_id < 1:
        raise ValueError("round_id beginnt bei 1")
    if (
        isinstance(build_mode, AgentBuildMode)
        and isinstance(reviewer, AgentReviewer)
        and build_mode.session_id == reviewer.session_id
    ):
        raise ValueError(
            "Bau und Review brauchen unabhaengige Sitzungen"
        )
    report = build_mode.build(BuildRequest(task, round_id, objection))
    context = context_after_build()
    if context.task != task.task:
        raise LoopProtocolError(
            "Nachweiskontext gehoert zu fremdem Auftrag"
        )
    if context.round_status.current != round_id:
        raise LoopProtocolError(
            "Nachweiskontext gehoert zu fremder Runde"
        )
    evidence = project_review_context(context, limits=limits)
    raw = reviewer.review(
        ReviewRequest(task, round_id, report, evidence)
    )
    return parse_review_decision(
        raw, run_id=task.run_id, round_id=round_id
    )


def parse_review_decision(
    raw: str, *, run_id: str, round_id: int
) -> ReviewDecision:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LoopProtocolError(
            "Review-Ausgabe ist kein einzelnes JSON-Objekt"
        ) from exc
    expected = {"run_id", "round_id", "action", "detail"}
    if not isinstance(value, dict) or set(value) != expected:
        raise LoopProtocolError(
            "Review-Ausgabe hat nicht exakt die erwarteten Felder"
        )
    received_round = value["round_id"]
    if (
        value["run_id"] != run_id
        or isinstance(received_round, bool)
        or not isinstance(received_round, int)
        or received_round != round_id
    ):
        raise LoopProtocolError(
            "Review-Ausgabe gehoert zu fremdem Lauf oder fremder Runde"
        )
    if not isinstance(value["detail"], str):
        raise LoopProtocolError("detail muss Text sein")
    try:
        action = ReviewAction(value["action"])
    except (ValueError, TypeError) as exc:
        raise LoopProtocolError("action ist ungueltig") from exc
    if action is not ReviewAction.PASS and not value["detail"].strip():
        raise LoopProtocolError(
            f"{action.value} braucht eine Begruendung"
        )
    return ReviewDecision(run_id, round_id, action, value["detail"])


def _build_prompt(request: BuildRequest) -> str:
    task = request.task
    sources = (
        "\n".join(f"- {source}" for source in task.sources) or "- keine"
    )
    objection = request.objection or "keine"
    heading = (
        f"Bauauftrag fuer Lauf {task.run_id}, Runde {request.round_id}."
    )
    return f"""{heading}
Arbeitsverzeichnis: {task.workdir}
Zugriffsprofil: {task.access_profile}
Diese Angaben beschreiben den erlaubten Lauf.
Der Prompt ist keine technische Zugriffssperre.

Gesamtauftrag:
{task.task}

Massgebliche Quellen:
{sources}

Offene Beanstandung: {objection}
Bearbeite den Auftrag und pruefe seine Wirkung.
Berichte knapp, was getan und geprueft wurde.
"""


def _review_prompt(request: ReviewRequest) -> str:
    task = request.task
    sources = "\n".join(f"- {source}" for source in task.sources)
    if not sources:
        sources = "- keine"
    heading = (
        f"Unabhaengiger Review fuer Lauf {task.run_id}, "
        f"Runde {request.round_id}."
    )
    return f"""{heading}
Arbeitsverzeichnis: {task.workdir}
Zugriffsprofil: {task.access_profile}
Diese Angaben beschreiben den erlaubten Lauf.
Der Prompt ist keine technische Zugriffssperre.
Pruefe Wirkung, Tests und Quellen gegen den vollstaendigen Auftrag.
Die Projektion ist begrenzt;
behaupte bei fehlendem Nachweis keinen Vollreview.

MASSGEBLICHE QUELLEN
{sources}

BAUBERICHT
{request.build_report.summary}

BEGRENZTE NACHWEISPROJEKTION
{request.evidence.text}

Antworte ausschliesslich als JSON-Objekt mit exakt diesen Feldern:
{{"run_id":"{task.run_id}","round_id":{request.round_id},"action":"PASS|CHANGES|NEEDS_DECISION|ESCALATE","detail":"..."}}
"""
