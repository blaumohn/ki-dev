"""Executor-unabhaengiger Einstieg in genau einen Agenten-Turn.

Der Aufrufer nennt nur den Transport (``claude-cli``, ``codex-cli``)
plus ``session``, ``message``, ``model`` und ``effort``. Die konkrete
Adapterklasse und jedes CLI-Argument bleiben hinter dieser Grenze;
welcher Executor-Name welchen Transport nutzt, deklariert
``adapter/executors.toml``.
"""

from __future__ import annotations

from pathlib import Path

from .base import CliAdapter
from .claude_cli import ClaudeCliAdapter
from .codex_cli import CodexCliAdapter
from .contract import Effort, TurnRequest, TurnResult

_ADAPTERS: dict[str, type[CliAdapter]] = {
    adapter.name: adapter
    for adapter in (ClaudeCliAdapter, CodexCliAdapter)
}


def cli_transports() -> dict[str, type[CliAdapter]]:
    """Die CLI-Transporte nach Namen."""
    return dict(_ADAPTERS)


def build_executor(
    transport: str,
    **adapter_kwargs: object,
) -> CliAdapter:
    """Erzeuge den Adapter zum Transportnamen.

    Ein unbekannter Name bricht ausdruecklich ab (kein stiller
    Standard-Transport).
    """
    try:
        adapter_cls = _ADAPTERS[transport]
    except KeyError:
        known = ", ".join(sorted(_ADAPTERS))
        raise ValueError(
            f"Unbekannter transport {transport!r}; bekannt: {known}"
        ) from None
    return adapter_cls(**adapter_kwargs)  # type: ignore[arg-type]


def send_turn(
    transport: str,
    *,
    session: str,
    message: str,
    model: str,
    effort: Effort,
    workdir: Path,
    env: dict[str, str] | None = None,
    **adapter_kwargs: object,
) -> TurnResult:
    """Fuehre genau einen Turn beim genannten Transport aus."""
    request = TurnRequest(
        session_id=session,
        message=message,
        model=model,
        effort=effort,
        workdir=workdir,
        env=env or {},
    )
    adapter = build_executor(transport, **adapter_kwargs)
    return adapter.send_turn(request)
