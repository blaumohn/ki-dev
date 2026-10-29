"""Anbieterneutraler Einstieg in Sitzungstranskripte.

Unabhaengig von ``cli_transports()``: ein Anbieter kann Turns
ausfuehren, ohne Transkripte zu liefern, und umgekehrt. Jede
anbieterspezifische Einzelheit bleibt hinter dieser Dispatch-Grenze.
"""

from __future__ import annotations

from collections.abc import Callable

from .claude_sessions import validate_claude_session_id
from .claude_transcript import read_claude_session
from .claude_transcript import (
    transcript_from_bytes as claude_from_bytes,
)
from .codex_sessions import validate_codex_session_id
from .codex_transcript import read_codex_session
from .codex_transcript import transcript_from_bytes as codex_from_bytes
from .session_catalog import SessionRef
from .session_transcript import (
    SessionTranscript,
    TranscriptError,
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
_PARSERS: dict[str, Callable[[str, bytes], SessionTranscript]] = {
    "codex": codex_from_bytes,
    "claude": claude_from_bytes,
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


def read_session_source(ref: SessionRef) -> bytes:
    """Katalogquelle direkt lesen; Konfiguration und Suche entfallen."""
    try:
        return ref.path.read_bytes()
    except OSError as exc:
        raise TranscriptError(
            (
                f"{ref.agent}-Sitzung nicht lesbar "
                f"({type(exc).__name__})",
            )
        ) from None


def parse_session_source(
    ref: SessionRef, data: bytes
) -> SessionTranscript:
    """Quelle normalisieren und mehrdeutige IDs ablehnen."""
    validate_session_request(ref.agent, ref.session_id)
    if ref.ambiguous:
        raise TranscriptError(
            (f"{ref.agent}-Sitzungsdatei ist mehrdeutig",)
        )
    return _PARSERS[ref.agent](ref.session_id, data)
