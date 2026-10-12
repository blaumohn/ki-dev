"""Adapter ``claude`` und ``codex``: Bau und Review über eine
vorbereitete Agentensitzung eines CLI-Executors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from ki_dev.adapter.contract import (
    AgentTurnError,
    ReviewRequest,
    TurnPrompt,
    WorkReport,
    WorkRequest,
)
from ki_dev.adapter.executors import (
    Effort,
    Executor,
    ExecutorSpec,
    TurnRequest,
)
from ki_dev.adapter.executors.contract import TurnBudget, TurnResult


@dataclass
class AgentWorker:
    executor: Executor
    session_id: str
    model: str
    effort: Effort
    budget: TurnBudget = TurnBudget()
    last_result: TurnResult | None = None
    spec: ExecutorSpec = field(kw_only=True)

    def work(self, request: WorkRequest) -> WorkReport:
        task = request.task
        return WorkReport(
            _send(self, request.prompt, task.workdir, task.env)
        )


@dataclass
class AgentReviewer:
    executor: Executor
    session_id: str
    model: str
    effort: Effort
    budget: TurnBudget = TurnBudget()
    last_result: TurnResult | None = None
    spec: ExecutorSpec = field(kw_only=True)

    def review(self, request: ReviewRequest) -> str:
        return _send(
            self, request.prompt, request.task.workdir, request.task.env
        )


@dataclass
class AgentSession:
    """Übergaben jeder Rolle an eine vorbereitete Agentensitzung."""

    executor: Executor
    session_id: str
    model: str
    effort: Effort
    budget: TurnBudget = TurnBudget()
    last_result: TurnResult | None = None
    spec: ExecutorSpec = field(kw_only=True)

    def ask(self, request: TurnPrompt) -> str:
        return _send(self, request.prompt, request.workdir, request.env)


def _send(
    agent: AgentWorker | AgentReviewer | AgentSession,
    message: str,
    workdir: Path,
    env: Mapping[str, str],
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
        )
    )
    agent.last_result = result
    if not result.ok:
        raise AgentTurnError(result)
    return result.stdout
