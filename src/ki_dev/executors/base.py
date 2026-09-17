"""Gemeinsame Basis fuer die CLI-Executor-Adapter.

Die Basis kapselt nur den executor-unabhaengigen Teil: den
Prozesslauf und die Weitergabe von ``stdin`` und Timeout. Die
vollstaendige Argumentbildung liegt in der jeweiligen Unterklasse.
"""

from __future__ import annotations

import math
import os
from abc import ABC, abstractmethod
from collections.abc import Callable

from .contract import (
    ContextMeasurement,
    ContextStatus,
    TurnRequest,
    TurnResult,
)
from .process import DEFAULT_TIMEOUT_S, run_cli_turn

ProcessRunner = Callable[..., TurnResult]


class CliAdapter(ABC):
    """Uebersetzt den Turn-Vertrag in genau einen CLI-Aufruf."""

    name: str = "cli"

    def __init__(
        self,
        *,
        executable: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        runner: ProcessRunner = run_cli_turn,
    ) -> None:
        if (
            type(timeout_s) not in (int, float)
            or not math.isfinite(timeout_s)
            or timeout_s <= 0
        ):
            raise ValueError("timeout_s muss positiv und endlich sein")
        self.executable = executable or self.default_executable
        self.timeout_s = timeout_s
        self._runner = runner

    def send_turn(self, request: TurnRequest) -> TurnResult:
        argv = [self.executable, *self.build_argv(request)]
        return self._runner(
            argv,
            stdin=self.message_stdin(request),
            timeout_s=min(self.timeout_s, request.budget.timeout_s)
            if request.budget
            else self.timeout_s,
            cwd=request.workdir,
            env={**os.environ, **request.env}
            if request.env
            else None,
        )

    @property
    @abstractmethod
    def default_executable(self) -> str:
        """Name der lokal installierten, bereits angemeldeten CLI."""

    @abstractmethod
    def build_argv(self, request: TurnRequest) -> list[str]:
        """Executor-spezifische Argumente ohne das Programm selbst."""

    def message_stdin(self, request: TurnRequest) -> str:
        return request.message

    def measure_context(self, session_id: str) -> ContextMeasurement:
        """Sitzungsbezogener Kontextmesswert; ``UNSUPPORTED`` als
        sicherer Standard fuer Adapter ohne eigene Messung."""
        del session_id
        return ContextMeasurement(ContextStatus.UNSUPPORTED)
