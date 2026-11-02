"""Adapter ``claude`` und ``codex``: Bau und Review über eine
Agentensitzung eines CLI-Executors.

Ohne ``session_id`` legt der erste Aufruf die Sitzung an; nach seinem
Erfolg gilt ihre ID für alle weiteren Aufrufe der Rolle und geht an
``on_session`` (der Ausführer legt sie im Lauf ab)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from ki_dev.adapter.contract import (
    AgentTurnError,
    ReviewRequest,
    TurnPrompt,
    WorkReport,
    WorkRequest,
    parse_work_report,
)
from ki_dev.adapter.executors import (
    Access,
    Effort,
    Executor,
    ExecutorSpec,
    TurnRequest,
)
from ki_dev.adapter.executors.contract import (
    ContextMeasurement,
    QuotaMeasurement,
    TurnBudget,
    TurnResult,
)


@dataclass
class AgentWorker:
    executor: Executor
    session_id: str | None
    model: str
    effort: Effort
    budget: TurnBudget = TurnBudget()
    last_result: TurnResult | None = None
    spec: ExecutorSpec = field(kw_only=True)
    on_session: Callable[[str], None] | None = field(
        default=None, kw_only=True
    )

    def work(self, request: WorkRequest) -> WorkReport:
        task = request.task
        access = Access(task.access_profile)
        return parse_work_report(
            _send(self, request.prompt, task.workdir, task.env, access)
        )


@dataclass
class AgentReviewer:
    executor: Executor
    session_id: str | None
    model: str
    effort: Effort
    budget: TurnBudget = TurnBudget()
    last_result: TurnResult | None = None
    spec: ExecutorSpec = field(kw_only=True)
    on_session: Callable[[str], None] | None = field(
        default=None, kw_only=True
    )

    def review(self, request: ReviewRequest) -> str:
        """Das Review prüft und ändert nichts: nur Lesezugriff."""
        return _send(
            self,
            request.prompt,
            request.task.workdir,
            request.task.env,
            Access.READ,
            request.output_schema,
        )


@dataclass
class AgentSession:
    """Übergaben jeder Rolle an eine vorbereitete Agentensitzung."""

    executor: Executor
    session_id: str | None
    model: str
    effort: Effort
    budget: TurnBudget = TurnBudget()
    last_result: TurnResult | None = None
    spec: ExecutorSpec = field(kw_only=True)
    on_session: Callable[[str], None] | None = field(
        default=None, kw_only=True
    )

    def ask(self, request: TurnPrompt) -> str:
        return _send(
            self, request.prompt, request.workdir, request.env, None
        )

    def measure_context(self) -> ContextMeasurement | None:
        """Kontext der Sitzung; vor dem ersten Aufruf (keine
        Sitzung) gibt es keinen."""
        if self.session_id is None:
            return None
        return self.executor.measure_context(self.session_id)

    def measure_quota(self) -> QuotaMeasurement:
        return self.executor.measure_quota(self.session_id)


def _send(
    agent: AgentWorker | AgentReviewer | AgentSession,
    message: str,
    workdir: Path,
    env: Mapping[str, str],
    access: Access | None,
    output_schema: Mapping[str, object] | None = None,
) -> str:
    """Ein Aufruf der Sitzung; das Ergebnis bleibt für Messung und
    Verbrauch am Adapter (``last_result``)."""
    agent.last_result = None
    result = agent.executor.send_turn(
        TurnRequest(
            session_id=agent.session_id,
            model=agent.model,
            effort=agent.effort,
            message=message,
            workdir=workdir,
            env=dict(env),
            budget=agent.budget,
            access=access,
            output_schema=output_schema,
        )
    )
    agent.last_result = result
    if not result.ok:
        raise AgentTurnError(result)
    if agent.session_id is None:
        _adopt_session(agent, result)
    return result.stdout


def _adopt_session(
    agent: AgentWorker | AgentReviewer | AgentSession,
    result: TurnResult,
) -> None:
    """Die neu angelegte Sitzung gilt nach dem ersten erfolgreichen
    Aufruf; ohne genannte ID wäre die Rolle nicht fortsetzbar."""
    if not result.session_id:
        raise AgentTurnError(
            replace(
                result,
                error="neue Sitzung angelegt, aber ohne Sitzungs-ID",
            )
        )
    agent.session_id = result.session_id
    if agent.on_session is not None:
        agent.on_session(result.session_id)
