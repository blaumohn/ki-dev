"""Ein einzelner, austauschbarer Bau--Review-Zyklus."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ki_dev.deltas import ControllerContext
from ki_dev.executors import Effort, Executor, TurnRequest
from ki_dev.executors.contract import TurnBudget, TurnResult
from ki_dev.review_context import (
    DEFAULT_PROJECTION_LIMITS,
    ProjectionLimits,
    ReviewProjection,
    project_review_context,
)
from ki_dev.review_decision import (
    LOOP_ACTIONS,
    ReviewAction,
    ReviewContractError,
    bind_requirement,
    load_json_object,
    parse_verdict,
)


class LoopProtocolError(ValueError):
    """Agentenausgabe verletzt Huelle oder Referenzbindung."""


class AgentTurnError(RuntimeError):
    """Agentenaufruf ohne Erlaubnis zur automatischen Wiederholung."""

    def __init__(self, result: TurnResult) -> None:
        self.result = result
        super().__init__(
            "; ".join(
                filter(
                    None,
                    (
                        result.error or result.status.value,
                        result.stderr[:2000],
                    ),
                )
            )
        )


@dataclass(frozen=True)
class LoopTask:
    run_id: str
    task: str
    sources: tuple[str, ...]
    workdir: Path
    access_profile: str
    acceptance_criteria: tuple[str, ...] = field(kw_only=True)
    env: dict[str, str] = field(kw_only=True, default_factory=dict)

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
        if not isinstance(
            self.acceptance_criteria, tuple
        ) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.acceptance_criteria
        ):
            raise TypeError(
                "LoopTask.acceptance_criteria muss ein Tupel "
                "nichtleerer Texte sein"
            )
        if not self.acceptance_criteria:
            raise ValueError(
                "LoopTask.acceptance_criteria darf nicht leer sein"
            )
        if len(set(self.acceptance_criteria)) != len(
            self.acceptance_criteria
        ):
            raise ValueError(
                "LoopTask.acceptance_criteria muss eindeutig sein"
            )
        if not isinstance(self.env, dict) or any(
            not isinstance(k, str) or not k or not isinstance(v, str)
            for k, v in self.env.items()
        ):
            raise TypeError(
                "LoopTask.env muss ein Mapping von Text auf Text sein"
            )

    def acceptance_criterion_ref(self, index: int) -> str:
        return f"AC{index}"

    def acceptance_criterion_refs(self) -> tuple[str, ...]:
        return tuple(
            self.acceptance_criterion_ref(i)
            for i in range(1, len(self.acceptance_criteria) + 1)
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
    requirement_ref: str | None = None


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
    budget: TurnBudget = TurnBudget()
    last_result: TurnResult | None = None

    def build(self, request: BuildRequest) -> BuildReport:
        self.last_result = None
        result = self.executor.send_turn(
            TurnRequest(
                session_id=self.session_id,
                model=self.model,
                effort=self.effort,
                message=_build_prompt(request),
                workdir=request.task.workdir,
                env=request.task.env,
                budget=self.budget,
            )
        )
        self.last_result = result
        if not result.ok:
            raise AgentTurnError(result)
        return BuildReport(result.stdout)


@dataclass
class AgentReviewer:
    executor: Executor
    session_id: str
    model: str
    effort: Effort
    budget: TurnBudget = TurnBudget()
    last_result: TurnResult | None = None

    def review(self, request: ReviewRequest) -> str:
        self.last_result = None
        result = self.executor.send_turn(
            TurnRequest(
                session_id=self.session_id,
                model=self.model,
                effort=self.effort,
                message=_review_prompt(request),
                workdir=request.task.workdir,
                env=request.task.env,
                budget=self.budget,
            )
        )
        self.last_result = result
        if not result.ok:
            raise AgentTurnError(result)
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
    decision = parse_review_decision(
        raw, run_id=task.run_id, round_id=round_id
    )
    return bind_review_decision(decision, task)


def parse_review_decision(
    raw: str, *, run_id: str, round_id: int
) -> ReviewDecision:
    """Loop-Hülle (run_id, round_id) prüfen, dann den gemeinsamen Kern
    aus review_decision; Vertragsfehler werden LoopProtocolError."""
    try:
        value = load_json_object(raw)
        _check_identity(value, run_id, round_id)
        core = {k: v for k, v in value.items() if k not in _IDENTITY}
        verdict = parse_verdict(core, LOOP_ACTIONS)
    except ReviewContractError as exc:
        raise LoopProtocolError(str(exc)) from exc
    return ReviewDecision(
        run_id,
        round_id,
        verdict.action,
        verdict.detail,
        verdict.requirement_ref,
    )


_IDENTITY = ("run_id", "round_id")


def _check_identity(value: dict, run_id: str, round_id: int) -> None:
    if any(key not in value for key in _IDENTITY):
        raise ReviewContractError(
            "Review-Ausgabe hat nicht exakt die erwarteten Felder"
        )
    received_round = value["round_id"]
    if (
        value["run_id"] != run_id
        or isinstance(received_round, bool)
        or not isinstance(received_round, int)
        or received_round != round_id
    ):
        raise ReviewContractError(
            "Review-Ausgabe gehoert zu fremdem Lauf oder fremder Runde"
        )


def bind_review_decision(
    decision: ReviewDecision, task: LoopTask
) -> ReviewDecision:
    """CHANGES an ein Abnahmekriterium des Laufs binden (gemeinsame
    Regel ``bind_requirement``)."""
    return bind_requirement(decision, task.acceptance_criterion_refs())


def _build_prompt(request: BuildRequest) -> str:
    task = request.task
    sources = (
        "\n".join(f"- {source}" for source in task.sources) or "- keine"
    )
    criteria = "\n".join(
        f"- {ref}: {text}"
        for ref, text in zip(
            task.acceptance_criterion_refs(),
            task.acceptance_criteria,
            strict=True,
        )
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

Abnahmekriterien:
{criteria}

Massgebliche Quellen:
{sources}

Offene Beanstandung: {objection}
Bearbeite den Auftrag und pruefe seine Wirkung.
Arbeite innerhalb der Aufrufgrenzen. Bei fehlendem Zugriff oder
anderem Blocker beende die Arbeit mit einer konkreten Begruendung;
versuche nicht wiederholt, denselben Blocker zu umgehen.
Berichte knapp, was getan und geprueft wurde.
"""


def _review_prompt(request: ReviewRequest) -> str:
    task = request.task
    sources = "\n".join(f"- {source}" for source in task.sources)
    if not sources:
        sources = "- keine"
    criteria = "\n".join(
        f"- {ref}: {text}"
        for ref, text in zip(
            task.acceptance_criterion_refs(),
            task.acceptance_criteria,
            strict=True,
        )
    )
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

BESTEHENDE ABNAHMEKRITERIEN (nur diese sind fuer CHANGES bindbar)
{criteria}

BAUBERICHT
{request.build_report.summary}

BEGRENZTE NACHWEISPROJEKTION
{request.evidence.text}

CHANGES braucht eine konkrete Bindung: welches der obigen Kriterien
ist verletzt, welches Verhalten wurde beobachtet, welcher Nachweis
belegt das. Ein Quelltext-Diff allein ist kein Ablehnungsgrund. Passt
die Beanstandung zu keinem bestehenden Kriterium oder verlangt sie
eine strengere neue Interpretation, antworte mit NEEDS_DECISION statt
CHANGES.

requirement_ref ist nur bei CHANGES gesetzt (sonst null).
Antworte ausschliesslich als JSON-Objekt mit exakt diesen Feldern:
{{"run_id":"{task.run_id}","round_id":{request.round_id},"action":"PASS|CHANGES|NEEDS_DECISION|ESCALATE","detail":"...","requirement_ref":"AC<n>|null"}}
"""
