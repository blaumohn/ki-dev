"""Codex-CLI-Adapter fuer vorbereitete Sitzungen.

Die unterstuetzte CLI-Syntax ist in ``docs/cli-adapters.md``
dokumentiert. Der Adapter nutzt ausschliesslich die lokal
installierte, bereits angemeldete ``codex``-CLI.
"""

from __future__ import annotations

from .base import CliAdapter
from .contract import TurnRequest

# Lokal verifizierter Bezugsstand der dokumentierten CLI-Syntax.
VERIFIED_CLI_VERSION = "0.152.1"


class CodexCliAdapter(CliAdapter):
    """Setzt eine vorbereitete Codex-CLI-Sitzung einen Turn fort."""

    name = "codex-cli"
    verified_cli_version = VERIFIED_CLI_VERSION

    @property
    def default_executable(self) -> str:
        return "codex"

    def build_argv(self, request: TurnRequest) -> list[str]:
        # ``-`` weist ``codex exec`` an, den Prompt von stdin zu
        # lesen. Effort geht direkt als Codex-Konfigurationsschluessel
        # ``model_reasoning_effort`` mit.
        return [
            "exec",
            "resume",
            request.session_id,
            "--model",
            request.model,
            "-c",
            f"model_reasoning_effort={request.effort.value}",
            "-",
        ]
