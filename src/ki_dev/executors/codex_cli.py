"""Codex-CLI-Adapter fuer vorbereitete Sitzungen.

Die unterstuetzte CLI-Syntax ist in ``docs/cli-adapters.md``
dokumentiert. Der Adapter nutzt ausschliesslich die lokal
installierte, bereits angemeldete ``codex``-CLI.
"""

from __future__ import annotations

from pathlib import Path

from .base import CliAdapter
from .contract import (
    QuotaMeasurement,
    QuotaStatus,
    TurnRequest,
    TurnResult,
)
from .metering import codex_quota, codex_result

# Lokal verifizierter Bezugsstand der dokumentierten CLI-Syntax.
VERIFIED_CLI_VERSION = "0.154.0"


class CodexCliAdapter(CliAdapter):
    """Setzt eine vorbereitete Codex-CLI-Sitzung einen Turn fort.

    Ohne native Turn-/Kosten-/Kontextgrenzen (siehe
    ``docs/cli-adapters.md``) bietet Codex keine lokale, vergleichbare
    Kontextmessung wie Claudes Sitzungsprotokoll; ``measure_context``
    bleibt deshalb bewusst beim ``UNSUPPORTED``-Standard aus
    ``CliAdapter`` statt eine ungeprüfte Messquelle zu erfinden.

    ``measure_quota`` dagegen liest den zuletzt bekannten
    5h-Kontingentverbrauch aus der lokalen Rollout-Ablage
    (``metering.codex_quota``, verbrauchsfrei) -- Codex fuehrt diesen
    Nachweis anders als den Kontext, siehe ``docs/cli-adapters.md``.
    """

    name = "codex-cli"
    verified_cli_version = VERIFIED_CLI_VERSION

    @property
    def default_executable(self) -> str:
        return "codex"

    def measure_quota(self, session_id: str) -> QuotaMeasurement:
        try:
            used_percent, resets_at = codex_quota(
                session_id, Path.home() / ".codex/sessions"
            )
        except (OSError, ValueError) as exc:
            return QuotaMeasurement(
                QuotaStatus.UNAVAILABLE, detail=str(exc)
            )
        return QuotaMeasurement(
            QuotaStatus.MEASURED,
            used_percent=used_percent,
            resets_at=resets_at,
        )

    def send_turn(self, request: TurnRequest) -> TurnResult:
        result = super().send_turn(request)
        return codex_result(result) if request.budget else result

    def build_argv(self, request: TurnRequest) -> list[str]:
        # ``-`` weist ``codex exec`` an, den Prompt von stdin zu
        # lesen. Effort geht direkt als Codex-Konfigurationsschluessel
        # ``model_reasoning_effort`` mit.
        argv = [
            "exec",
            "resume",
            request.session_id,
            "--model",
            request.model,
            "-c",
            f"model_reasoning_effort={request.effort.value}",
            "-",
        ]
        if request.budget:
            argv.insert(-1, "--json")
        return argv
