from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from ki_dev.adapter.executors import TurnResult, TurnStatus
from ki_dev.adapter.executors.claude_cli import ClaudeCliAdapter
from ki_dev.adapter.executors.codex_cli import CodexCliAdapter

# ``--version``-Antwort der echten CLIs im geprüften Stand.
_VERSION_OUTPUT = {
    "claude": f"{ClaudeCliAdapter.cli_version_pin} (Claude Code)",
    "codex": f"codex-cli {CodexCliAdapter.cli_version_pin}",
}


class FakeRunner:
    """Zeichnet den CLI-Aufruf auf, ohne einen Prozess zu starten.

    Die Versionsprobe beantwortet er wie die CLI im geprüften Stand;
    jeder andere Aufruf erhält ``result``."""

    def __init__(self, result: TurnResult | None = None) -> None:
        self.result = result or TurnResult(
            status=TurnStatus.OK,
            exit_code=0,
            stdout="",
            stderr="",
            argv=(),
            duration_s=0.0,
        )
        self.calls: list[tuple[tuple[str, ...], str, float]] = []
        self.kwargs: list[dict[str, object]] = []

    def __call__(
        self,
        argv: list[str],
        *,
        stdin: str,
        timeout_s: float,
        **kwargs: object,
    ) -> TurnResult:
        self.calls.append((tuple(argv), stdin, timeout_s))
        self.kwargs.append(kwargs)
        program = Path(argv[0]).name
        if argv[1:] == ["--version"] and program in _VERSION_OUTPUT:
            return replace(
                self.result,
                status=TurnStatus.OK,
                exit_code=0,
                stdout=_VERSION_OUTPUT[program],
                error=None,
            )
        return self.result

    @property
    def argv(self) -> tuple[str, ...]:
        return self.calls[-1][0]

    @property
    def stdin(self) -> str:
        return self.calls[-1][1]

    @property
    def last_kwargs(self) -> dict[str, object]:
        return self.kwargs[-1]

    def value_after(self, flag: str) -> str:
        argv = self.argv
        return argv[argv.index(flag) + 1]
