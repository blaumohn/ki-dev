"""Executor-Adapter fuer genau einen synchronen Agenten-Turn."""

from __future__ import annotations

from .base import CliAdapter, ProcessRunner
from .claude_cli import ClaudeCliAdapter
from .codex_cli import CodexCliAdapter
from .contract import (
    Effort,
    Executor,
    TurnRequest,
    TurnResult,
    TurnStatus,
)
from .dispatch import available_executors, build_executor, send_turn
from .process import DEFAULT_TIMEOUT_S, run_cli_turn

__all__ = [
    "DEFAULT_TIMEOUT_S",
    "CliAdapter",
    "ClaudeCliAdapter",
    "CodexCliAdapter",
    "Effort",
    "Executor",
    "ProcessRunner",
    "TurnRequest",
    "TurnResult",
    "TurnStatus",
    "available_executors",
    "build_executor",
    "run_cli_turn",
    "send_turn",
]
