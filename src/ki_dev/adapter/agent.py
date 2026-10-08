"""Adapter ``claude`` und ``codex``: Bau und Review über eine
vorbereitete Agentensitzung eines CLI-Executors."""

from __future__ import annotations

from dataclasses import dataclass

from ki_dev.adapter.contract import (
    AgentTurnError,
    ReviewRequest,
    WorkReport,
    WorkRequest,
)
from ki_dev.adapter.executors import Effort, Executor, TurnRequest
from ki_dev.adapter.executors.contract import TurnBudget, TurnResult
from ki_dev.adapter.prompts import review_prompt, work_prompt


@dataclass
class AgentWorker:
    executor: Executor
    session_id: str
    model: str
    effort: Effort
    budget: TurnBudget = TurnBudget()
    last_result: TurnResult | None = None

    def work(self, request: WorkRequest) -> WorkReport:
        self.last_result = None
        result = self.executor.send_turn(
            TurnRequest(
                session_id=self.session_id,
                model=self.model,
                effort=self.effort,
                message=work_prompt(request),
                workdir=request.task.workdir,
                env=request.task.env,
                budget=self.budget,
            )
        )
        self.last_result = result
        if not result.ok:
            raise AgentTurnError(result)
        return WorkReport(result.stdout)


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
                message=review_prompt(request),
                workdir=request.task.workdir,
                env=request.task.env,
                budget=self.budget,
            )
        )
        self.last_result = result
        if not result.ok:
            raise AgentTurnError(result)
        return result.stdout
