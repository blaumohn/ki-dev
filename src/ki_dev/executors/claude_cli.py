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
    QuotaMeasurement,
    QuotaStatus,
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

    def measure_quota(self, session_id: str) -> QuotaMeasurement:
        """Kein verbrauchsfreier, nicht-interaktiver Nachweis bekannt.

        Claude Code liefert ``rate_limits.five_hour.used_percentage``
        nachweislich nur an ein interaktives ``statusLine``-Skript und
        ``/usage`` (Claude-Code-Changelog 2.1.80); die lokale
        Sitzungsablage (``~/.claude/projects/*/<session_id>.jsonl``)
        traegt dieses Feld auch bei Erfolg nicht, sondern nur reaktiv
        im Fehlerfall (``quotaLimits`` bei HTTP 429) -- zu spaet fuer
        eine Vorabpruefung. Solange kein verbrauchsfreier,
        nicht-interaktiver Messweg verifiziert ist, bleibt dieser
        Executor ``UNSUPPORTED``; anders als bei ``measure_context``
        blockiert das hier jeden weiteren Aufruf, siehe
        ``QuotaStatus`` (ki-dev-ablauf-hju).
        """
        del session_id
        return QuotaMeasurement(
            QuotaStatus.UNSUPPORTED,
            detail=(
                "claude-cli liefert keinen verbrauchsfreien, "
                "nicht-interaktiven 5h-Kontingentmesswert"
            ),
        )

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
