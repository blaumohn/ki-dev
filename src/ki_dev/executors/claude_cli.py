"""Claude-CLI-Adapter fuer vorbereitete Sitzungen.

Die unterstuetzte CLI-Syntax ist in ``docs/cli-adapters.md``
dokumentiert. Der Adapter nutzt ausschliesslich die lokal
installierte, bereits angemeldete ``claude``-CLI.
"""

from __future__ import annotations

from pathlib import Path

from .base import CliAdapter
from .contract import TurnRequest, TurnResult, TurnStatus
from .metering import claude_context_tokens, claude_result

# Lokal verifizierter Bezugsstand der dokumentierten CLI-Syntax.
VERIFIED_CLI_VERSION = "2.1.272"


class ClaudeCliAdapter(CliAdapter):
    """Setzt eine vorbereitete Claude-Code-Sitzung einen Turn fort."""

    name = "claude-cli"
    verified_cli_version = VERIFIED_CLI_VERSION

    @property
    def default_executable(self) -> str:
        return "claude"

    def send_turn(self, request: TurnRequest) -> TurnResult:
        if request.budget is not None:
            try:
                tokens = claude_context_tokens(
                    request.session_id, Path.home() / ".claude/projects"
                )
                if tokens >= request.budget.max_context_tokens:
                    raise ValueError(
                        f"Sitzungskontext {tokens} >= Grenze "
                        f"{request.budget.max_context_tokens}; "
                        "Kontext vor Fortsetzung klaeren"
                    )
            except (OSError, ValueError) as exc:
                return TurnResult(
                    TurnStatus.START_ERROR,
                    None,
                    "",
                    "",
                    (),
                    0.0,
                    error=str(exc),
                    usage={
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                        "num_turns": 0,
                        "cost_usd": 0.0,
                    },
                )
        result = super().send_turn(request)
        return claude_result(result) if request.budget else result

    def build_argv(self, request: TurnRequest) -> list[str]:
        # Die Claude-CLI kennt ``--effort`` nativ (verifiziert mit
        # Claude Code 2.1.272; gueltige Stufen dort:
        # low/medium/high/xhigh/max). Die drei Vertragsstufen werden
        # unveraendert durchgereicht.
        argv = [
            "--print",
            "--output-format",
            "json" if request.budget else "text",
            "--model",
            request.model,
            "--resume",
            request.session_id,
            "--effort",
            request.effort.value,
        ]
        if request.budget:
            argv += [
                "--max-turns",
                str(request.budget.max_turns),
                "--max-budget-usd",
                str(request.budget.max_budget_usd),
            ]
        return argv
