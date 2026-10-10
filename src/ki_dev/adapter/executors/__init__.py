"""Executor-Adapter fuer genau einen synchronen Agenten-Turn."""

from __future__ import annotations

from .base import CliAdapter, ProcessRunner
from .claude_cli import ClaudeCliAdapter
from .codex_cli import CodexCliAdapter
from .contract import (
    Effort,
    Executor,
    ExecutorSpec,
    Measure,
    TurnRequest,
    TurnResult,
    TurnStatus,
)
from .dispatch import build_executor, cli_transports, send_turn
from .process import DEFAULT_TIMEOUT_S, run_cli_turn

__all__ = [
    "DEFAULT_TIMEOUT_S",
    "CliAdapter",
    "ClaudeCliAdapter",
    "CodexCliAdapter",
    "Effort",
    "Executor",
    "ExecutorSpec",
    "Measure",
    "ProcessRunner",
    "TurnRequest",
    "TurnResult",
    "TurnStatus",
    "build_executor",
    "cli_transports",
    "run_cli_turn",
    "send_turn",
]
