"""Codex-CLI-Adapter fuer vorbereitete Sitzungen.

Die unterstuetzte CLI-Syntax ist in ``docs/cli-adapters.md``
dokumentiert. Der Adapter nutzt ausschliesslich die lokal
installierte, bereits angemeldete ``codex``-CLI.
"""

from __future__ import annotations

import re
from pathlib import Path

from ki_dev.tool_versions import load_tool_versions

from .base import CliAdapter
from .contract import (
    Measure,
    QuotaMeasurement,
    QuotaStatus,
    TurnRequest,
    TurnResult,
)
from .metering import codex_quota, codex_result

# Gemeinsamer Versionsstand fuer Build und Laufzeit.
CLI_VERSION = load_tool_versions()["CODEX_VERSION"]

# Beobachtetes Format von ``codex --version``, z. B.
# "codex-cli 0.154.0".
_VERSION_OUTPUT = re.compile(r"^codex-cli\s+(\S+)")


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
    capabilities = frozenset({Measure.QUOTA, Measure.BUDGET})
    cli_version_pin = CLI_VERSION

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

    def parse_version(self, raw: str) -> str | None:
        match = _VERSION_OUTPUT.match(raw.strip())
        return match.group(1) if match else None

    def send_turn(self, request: TurnRequest) -> TurnResult:
        if not request.budget:
            return super().send_turn(request)
        cli_version, result, turn_ran = self.send_metered_turn(request)
        if not turn_ran:
            return result
        return codex_result(
            result,
            session_id=request.session_id,
            cli_version=cli_version,
        )

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
