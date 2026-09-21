"""Anbieterneutraler Einstieg in Sitzungstranskripte.

Unabhaengig von ``available_executors()``: ein Anbieter kann Turns
ausfuehren, ohne Transkripte zu liefern, und umgekehrt. Jede
anbieterspezifische Einzelheit bleibt hinter dieser Dispatch-Grenze.
"""

from __future__ import annotations

from collections.abc import Callable

from .codex_sessions import validate_codex_session_id
from .codex_transcript import read_codex_session
from .session_transcript import (
    SessionTranscript,
    TranscriptRequestError,
)

_VALIDATORS: dict[str, Callable[[str], None]] = {
    "codex": validate_codex_session_id,
}
_READERS: dict[str, Callable[[str], SessionTranscript]] = {
    "codex": read_codex_session,
}


def transcript_agents() -> tuple[str, ...]:
    """Anbieter, deren Sitzungen als Transkript gelesen werden."""
    return tuple(_READERS)


def validate_session_request(agent: str, session_id: str) -> None:
    """Prueft Anbieter und ID ohne Datei- oder Umgebungszugriff."""
    validator = _VALIDATORS.get(agent)
    if validator is None:
        raise TranscriptRequestError(
            f"Transkriptanbieter {agent!r} wird nicht unterstuetzt; "
            f"unterstuetzt: {', '.join(transcript_agents())}"
        )
    try:
        validator(session_id)
    except ValueError as exc:
        raise TranscriptRequestError(str(exc)) from None


def read_session_transcript(
    agent: str, session_id: str
) -> SessionTranscript:
    """Sitzung des Anbieters lesen, pruefen und normalisieren."""
    validate_session_request(agent, session_id)
    return _READERS[agent](session_id)
