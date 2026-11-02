"""Prozesslauf im Agent-Container: ``agent-container run CLI ARGS``.

Liegt unter dem Executor: Adapter und Prüfbefehle bauen ihren Aufruf
wie sonst, nur der Prozessstart setzt den Launcher davor. Der Launcher
bindet genau den Worktree ``cwd`` ein (docker/agent/README.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from uuid import uuid4

from .contract import TurnResult, TurnStatus
from .process import DEFAULT_TIMEOUT_S, run_cli_turn

STOP_TIMEOUT_S = 30.0


def default_launcher() -> Path:
    """Der Launcher, den ``make setup-runtime`` installiert."""
    configured = os.environ.get("XDG_DATA_HOME", "")
    data_home = (
        Path(configured)
        if os.path.isabs(configured)
        else Path.home() / ".local/share"
    )
    return data_home / "ki-dev/agent-container/scripts/agent-container"


@dataclass(frozen=True)
class ContainerProcess:
    """Gleiche Signatur wie :func:`run_cli_turn`, Lauf im Container.

    ``env`` enthält nur die Werte des Aufrufs: Die Host-Umgebung gehört
    nicht in den Container. Der Name je Aufruf erlaubt das Entfernen,
    wenn der Docker-Client stirbt, der Container aber weiterliefe.
    """

    launcher: Path

    def __call__(
        self,
        argv: list[str],
        *,
        stdin: str,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> TurnResult:
        if cwd is None:
            raise ValueError("Lauf im Container braucht ein workdir")
        name = f"ki-dev-{uuid4().hex[:12]}"
        command = self._command(argv, cwd, name, env or {})
        try:
            result = run_cli_turn(
                command, stdin=stdin, timeout_s=timeout_s, env=env
            )
        except BaseException as exc:
            problem = self._stop(name)
            if problem:
                exc.add_note(problem)
            raise
        if result.status is TurnStatus.OK:
            return result
        problem = self._stop(name)
        if problem:
            return replace(result, error=f"{result.error}; {problem}")
        return result

    def _command(
        self,
        argv: list[str],
        cwd: Path,
        name: str,
        env: dict[str, str],
    ) -> list[str]:
        forwarded = [
            argument
            for variable in sorted(env)
            for argument in ("--env", variable)
        ]
        return [
            str(self.launcher),
            "--workdir",
            str(cwd),
            "--name",
            name,
            *forwarded,
            "run",
            *argv,
        ]

    def _stop(self, name: str) -> str | None:
        """Container entfernen; ein Fehlschlag wird gemeldet, denn ein
        verbliebener Container verbraucht weiter Kontingent."""
        result = run_cli_turn(
            [str(self.launcher), "stop", name],
            stdin="",
            timeout_s=STOP_TIMEOUT_S,
        )
        if result.status is TurnStatus.OK:
            return None
        return f"Container {name} nicht entfernt: {result.error}"
