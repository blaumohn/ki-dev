"""Anbieterneutraler Einstieg in Sitzungstranskripte.

Unabhaengig von ``cli_transports()``: ein Anbieter kann Turns
ausfuehren, ohne Transkripte zu liefern, und umgekehrt. Jede
anbieterspezifische Einzelheit bleibt hinter dieser Dispatch-Grenze.
"""

from __future__ import annotations

from collections.abc import Callable

from .claude_sessions import validate_claude_session_id
from .claude_transcript import read_claude_session
from .codex_sessions import validate_codex_session_id
from .codex_transcript import read_codex_session
from .session_transcript import (
    SessionTranscript,
    TranscriptRequestError,
)

_VALIDATORS: dict[str, Callable[[str], None]] = {
    "codex": validate_codex_session_id,
    "claude": validate_claude_session_id,
}
_READERS: dict[str, Callable[[str], SessionTranscript]] = {
    "codex": read_codex_session,
    "claude": read_claude_session,
}


def transcript_agents() -> tuple[str, ...]:
    """Anbieter, deren Sitzungen als Transkript gelesen werden."""
    return tuple(_READERS)


def validate_agent(agent: str) -> None:
    """Prueft den Anbieter ohne Datei- oder Umgebungszugriff."""
    if agent not in _READERS:
        raise TranscriptRequestError(
            f"Transkriptanbieter {agent!r} wird nicht unterstuetzt; "
            f"unterstuetzt: {', '.join(transcript_agents())}"
        )


def validate_session_request(agent: str, session_id: str) -> None:
    """Prueft Anbieter und ID ohne Datei- oder Umgebungszugriff."""
    validate_agent(agent)
    try:
        _VALIDATORS[agent](session_id)
    except ValueError as exc:
        raise TranscriptRequestError(str(exc)) from None


def read_session_transcript(
    agent: str, session_id: str
) -> SessionTranscript:
    """Sitzung des Anbieters lesen, pruefen und normalisieren."""
    validate_session_request(agent, session_id)
    return _READERS[agent](session_id)
