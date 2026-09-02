"""Executor-unabhaengiger Einstieg in genau einen Agenten-Turn.

Der Aufrufer nennt nur ``executor`` als Namen plus ``session``,
``message``, ``model`` und ``effort``. Die konkrete Adapterklasse und
jedes executor-spezifische CLI-Argument bleiben hinter dieser Grenze.
"""

from __future__ import annotations

from .base import CliAdapter
from .claude_cli import ClaudeCliAdapter
from .codex_cli import CodexCliAdapter
from .contract import Effort, TurnRequest, TurnResult

_ADAPTERS: dict[str, type[CliAdapter]] = {
    "claude": ClaudeCliAdapter,
    "codex": CodexCliAdapter,
}


def available_executors() -> tuple[str, ...]:
    """Namen der bekannten Executor-Adapter."""
    return tuple(_ADAPTERS)


def build_executor(
    executor: str,
    **adapter_kwargs: object,
) -> CliAdapter:
    """Erzeuge den Adapter zum Executor-Namen.

    Ein unbekannter Name bricht ausdruecklich ab (kein stiller
    Standard-Executor).
    """
    try:
        adapter_cls = _ADAPTERS[executor]
    except KeyError:
        known = ", ".join(sorted(_ADAPTERS))
        raise ValueError(
            f"Unbekannter executor {executor!r}; bekannt: {known}"
        ) from None
    return adapter_cls(**adapter_kwargs)  # type: ignore[arg-type]


def send_turn(
    executor: str,
    *,
    session: str,
    message: str,
    model: str,
    effort: Effort,
    **adapter_kwargs: object,
) -> TurnResult:
    """Fuehre genau einen Turn beim genannten Executor aus."""
    request = TurnRequest(
        session_id=session,
        message=message,
        model=model,
        effort=effort,
    )
    return build_executor(executor, **adapter_kwargs).send_turn(request)
