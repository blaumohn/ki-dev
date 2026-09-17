"""Claude-CLI-Adapter fuer vorbereitete Sitzungen.

Die unterstuetzte CLI-Syntax ist in ``docs/cli-adapters.md``
dokumentiert. Der Adapter nutzt ausschliesslich die lokal
installierte, bereits angemeldete ``claude``-CLI.
"""

from __future__ import annotations

from pathlib import Path

from .base import CliAdapter
from .contract import (
    ContextMeasurement,
    ContextStatus,
    TurnRequest,
    TurnResult,
)
from .metering import claude_context_tokens, claude_result

# Lokal verifizierter Bezugsstand der dokumentierten CLI-Syntax.
VERIFIED_CLI_VERSION = "2.1.272"


class ClaudeCliAdapter(CliAdapter):
    """Setzt eine vorbereitete Claude-Code-Sitzung einen Turn fort.

    Die Kontextvorpruefung selbst ist keine Aufgabe dieses Adapters
    mehr: ``measure_context`` liefert nur den Messwert, Freigabe/Halt
    entscheidet die technische Orchestrierung (``loop_runtime``,
    ki-dev-ablauf-agu). Ein Adapter darf ueber sein eigenes Ergebnis
    nicht selbst befinden, ob der naechste Aufruf stattfindet.
    """

    name = "claude-cli"
    verified_cli_version = VERIFIED_CLI_VERSION

    @property
    def default_executable(self) -> str:
        return "claude"

    def measure_context(self, session_id: str) -> ContextMeasurement:
        try:
            tokens = claude_context_tokens(
                session_id, Path.home() / ".claude/projects"
            )
        except (OSError, ValueError) as exc:
            return ContextMeasurement(
                ContextStatus.UNAVAILABLE, detail=str(exc)
            )
        return ContextMeasurement(ContextStatus.MEASURED, tokens=tokens)

    def send_turn(self, request: TurnRequest) -> TurnResult:
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
