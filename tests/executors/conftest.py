from __future__ import annotations

from ki_dev.executors import TurnResult, TurnStatus


class FakeRunner:
    """Zeichnet den CLI-Aufruf auf, ohne einen Prozess zu starten."""

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

    def __call__(
        self,
        argv: list[str],
        *,
        stdin: str,
        timeout_s: float,
        **_: object,
    ) -> TurnResult:
        self.calls.append((tuple(argv), stdin, timeout_s))
        return self.result

    @property
    def argv(self) -> tuple[str, ...]:
        return self.calls[-1][0]

    @property
    def stdin(self) -> str:
        return self.calls[-1][1]

    def value_after(self, flag: str) -> str:
        argv = self.argv
        return argv[argv.index(flag) + 1]
