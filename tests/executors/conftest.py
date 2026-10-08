from __future__ import annotations

from ki_dev.adapter.executors import TurnResult, TurnStatus


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
