"""Claude-CLI-Adapter fuer vorbereitete Sitzungen.

Die unterstuetzte CLI-Syntax ist in ``docs/cli-adapters.md``
dokumentiert. Der Adapter nutzt ausschliesslich die lokal
installierte, bereits angemeldete ``claude``-CLI.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import replace
from pathlib import Path

from ki_dev.tool_versions import load_tool_versions

from .base import CliAdapter
from .contract import (
    ContextMeasurement,
    ContextStatus,
    QuotaMeasurement,
    QuotaStatus,
    TurnRequest,
    TurnResult,
)
from .metering import (
    claude_context_tokens,
    claude_result,
    claude_stream,
)

# Gemeinsamer Versionsstand fuer Build und Laufzeit.
CLI_VERSION = load_tool_versions()["CLAUDE_VERSION"]

# Beobachtetes Format von ``claude --version``, z. B.
# "2.1.272 (Claude Code)".
_VERSION_OUTPUT = re.compile(r"^(\S+)\s+\(Claude Code\)")

# Letzter 5h-Messwert je Sitzung, geschrieben nach jedem Turn.
DEFAULT_QUOTA_DIR = Path.home() / ".cache/ki-dev/claude-quota"


class ClaudeCliAdapter(CliAdapter):
    """Setzt eine vorbereitete Claude-Code-Sitzung einen Turn fort.

    Die Kontextvorpruefung selbst ist keine Aufgabe dieses Adapters
    mehr: ``measure_context`` liefert nur den Messwert, Freigabe/Halt
    entscheidet der Ausführer (``runner.runtime``,
    ki-dev-ablauf-agu). Ein Adapter darf ueber sein eigenes Ergebnis
    nicht selbst befinden, ob der naechste Aufruf stattfindet.
    """

    name = "claude-cli"
    cli_version_pin = CLI_VERSION

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

    def __init__(
        self, *, quota_dir: Path | None = None, **kwargs
    ) -> None:
        super().__init__(**kwargs)
        self.quota_dir = quota_dir or DEFAULT_QUOTA_DIR

    def measure_quota(self, session_id: str) -> QuotaMeasurement:
        """Letzter 5h-Wert aus der Antwort des vorigen Turns.

        Claude liefert den Wert verbrauchsfrei nur mit einer Antwort
        (``rate_limit_event`` in ``stream-json``), nie vorab. Darum
        ``PENDING`` vor dem ersten Turn und nach einem Fensterwechsel;
        ein Turn ohne Messwert laesst den letzten Wert stehen.
        """
        try:
            value = json.loads(
                self._quota_path(session_id).read_text(encoding="utf-8")
            )
        except FileNotFoundError:
            return QuotaMeasurement(
                QuotaStatus.PENDING,
                detail="noch kein Turn; Messung nach dem ersten",
            )
        except (OSError, ValueError) as exc:
            return QuotaMeasurement(
                QuotaStatus.UNAVAILABLE, detail=str(exc)
            )
        try:
            return _stored_quota(value)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            return QuotaMeasurement(
                QuotaStatus.UNAVAILABLE,
                detail=f"Messwertdatei ungueltig: {exc!r}",
            )

    def _quota_path(self, session_id: str) -> Path:
        return self.quota_dir / f"{session_id}.json"

    def _store_quota(
        self, session_id: str, quota: tuple[float, int] | None
    ) -> None:
        if quota is None:
            # Turn ohne Ereignis (Abbruch, Fehler): letzter Wert gilt.
            return
        value = {"used_percent": quota[0], "resets_at": quota[1]}
        path = self._quota_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def parse_version(self, raw: str) -> str | None:
        match = _VERSION_OUTPUT.match(raw.strip())
        return match.group(1) if match else None

    def send_turn(self, request: TurnRequest) -> TurnResult:
        if not request.budget:
            return super().send_turn(request)
        cli_version, result, turn_ran = self.send_metered_turn(request)
        if not turn_ran:
            return result
        result_line, quota = claude_stream(result.stdout)
        self._store_quota(request.session_id, quota)
        return claude_result(
            replace(result, stdout=result_line),
            session_id=request.session_id,
            cli_version=cli_version,
        )

    def build_argv(self, request: TurnRequest) -> list[str]:
        # Die Claude-CLI kennt ``--effort`` nativ (verifiziert mit
        # Claude Code 2.1.272; gueltige Stufen dort:
        # low/medium/high/xhigh/max). Die drei Vertragsstufen werden
        # unveraendert durchgereicht.
        argv = [
            "--print",
            "--output-format",
            "stream-json" if request.budget else "text",
            "--model",
            request.model,
            "--resume",
            request.session_id,
            "--effort",
            request.effort.value,
        ]
        if request.budget:
            argv += [
                "--verbose",
                "--max-turns",
                str(request.budget.max_turns),
                "--max-budget-usd",
                str(request.budget.max_budget_usd),
            ]
        return argv


def _stored_quota(value: dict) -> QuotaMeasurement:
    if value["resets_at"] <= time.time():
        return QuotaMeasurement(
            QuotaStatus.PENDING,
            detail="5h-Fenster abgelaufen; Messung nach dem Turn",
        )
    return QuotaMeasurement(
        QuotaStatus.MEASURED,
        used_percent=value["used_percent"],
        resets_at=value["resets_at"],
    )
