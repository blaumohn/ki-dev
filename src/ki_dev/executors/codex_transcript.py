"""Codex-Transkriptadapter: Dialog aus einer Sitzungs-JSONL lesen.

Fachliches Vorbild: der Extraktor ``codex-session-transcript.py``.
Unterstuetzt ist nur der enge Eingangsvertrag (Benutzer-``UserMessage``
und Assistenten-``final_answer``, Pruefungen T1-T7). Abweichungen sind
Plausibilitaets-/Formatfehler und werden ohne Reparatur gemeldet; ein
CLI-Versionswechsel ist damit nicht bewiesen. Diagnosen nennen nur
Pruefcode, Zeile, Feldpfad und Zaehler -- nie Gespraechsinhalte.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

from .codex_sessions import (
    find_session_rollouts,
    resolve_codex_sessions_dir,
    validate_codex_session_id,
)
from .session_transcript import (
    SessionTranscript,
    TranscriptError,
    TranscriptMessage,
)

AGENT = "codex"
PARSER_VERSION = "codex-dialog-1"
MAX_CASES = 10
_PHASES = {"final_answer"}
_KNOWN_PHASES = {"final_answer", "commentary"}
_FORMAT_NOTE = (
    "Hinweis: Plausibilitaets-/Formatabweichung gegenueber dem "
    "unterstuetzten Dialogformat; kein bewiesener CLI-Versionswechsel"
)


def read_codex_session(session_id: str) -> SessionTranscript:
    """Ein-/Ausgabegrenze: Umgebung und Datei nur hier gelesen.

    Erwartete Konfigurations- und Dateifehler werden zu bereinigten
    ``TranscriptError``; Ausnahmetexte des Betriebssystems (Pfade)
    gelangen nicht in die Meldung.
    """
    validate_codex_session_id(session_id)
    try:
        root = resolve_codex_sessions_dir(os.environ, Path.home())
    except (ValueError, RuntimeError) as exc:
        cause = _config_cause(exc)
        raise TranscriptError(
            (f"Codex-Sitzungsordner nicht bestimmbar: {cause}",)
        ) from None
    try:
        rollout = _single_rollout(root, session_id)
        data = rollout.read_bytes()
    except OSError as exc:
        raise TranscriptError(
            (f"Codex-Sitzung nicht lesbar ({type(exc).__name__})",)
        ) from None
    return transcript_from_bytes(session_id, data)


def _config_cause(exc: Exception) -> str:
    # ValueError stammt aus resolve_codex_sessions_dir und nennt nur
    # den Variablennamen; ein RuntimeError (kein Home) bleibt generisch.
    if isinstance(exc, ValueError):
        return str(exc)
    return "Home-Verzeichnis unbekannt"


def transcript_from_bytes(
    session_id: str, data: bytes
) -> SessionTranscript:
    """Reine Extraktion aus genau den Bytes, ueber die der Hash geht."""
    digest = hashlib.sha256(data).hexdigest()
    lines = _decode(data).split("\n")
    findings = _Findings()
    hits = _classify_lines(lines, data.endswith(b"\n"), findings)
    messages = _ordered_messages(hits, findings)
    findings.raise_if_any()
    return SessionTranscript(
        agent=AGENT,
        session_id=session_id,
        source_digest=digest,
        parser_version=PARSER_VERSION,
        messages=messages,
        diagnostics={
            "lines": data.count(b"\n") + (not data.endswith(b"\n")),
            "user_messages": _count(messages, "user"),
            "assistant_messages": _count(messages, "assistant"),
        },
    )


def _single_rollout(root: Path, session_id: str) -> Path:
    if not root.is_dir():
        raise TranscriptError(("Codex-Sitzungsordner existiert nicht",))
    found = find_session_rollouts(root, session_id)
    if not found:
        raise TranscriptError(("Codex-Sitzung nicht gefunden",))
    if len(found) > 1:
        raise TranscriptError(
            (f"Codex-Sitzung mehrdeutig ({len(found)} Treffer)",)
        )
    return found[0]


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TranscriptError(
            (f"J0 Datei ist kein gueltiges UTF-8 (Byte {exc.start})",)
        ) from None


@dataclass(frozen=True)
class _Hit:
    line: int
    role: str
    text: str
    turn: object
    ordinal: object


class _Findings:
    """Faelle je Pruefcode, je Pruefung hoechstens ``MAX_CASES``."""

    def __init__(self) -> None:
        self._by_code: dict[str, tuple[str, list[str], int]] = {}

    def add(self, code: str, title: str, case: str) -> None:
        _, cases, total = self._by_code.get(code, (title, [], 0))
        if len(cases) < MAX_CASES:
            cases.append(case)
        self._by_code[code] = (title, cases, total + 1)

    def problems(self) -> tuple[str, ...]:
        out = []
        for code, (title, cases, total) in sorted(
            self._by_code.items()
        ):
            omitted = total - len(cases)
            more = f"; {omitted} weitere ausgelassen" if omitted else ""
            out.append(
                f"{code} {title} ({total}x): " + "; ".join(cases) + more
            )
        return tuple(out)

    def has(self, code: str) -> bool:
        return code in self._by_code

    def raise_if_any(self) -> None:
        if self._by_code:
            raise TranscriptError(self.problems() + (_FORMAT_NOTE,))


def _classify_lines(
    lines: list[str], ends_with_newline: bool, findings: _Findings
) -> list[_Hit]:
    hits = []
    for number, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except (ValueError, RecursionError):
            partial = number == len(lines) and not ends_with_newline
            findings.add(
                "J1",
                "ungueltiges JSON",
                f"Zeile {number}"
                + (
                    " (letzte Zeile, evtl. unvollstaendig)"
                    if partial
                    else ""
                ),
            )
            continue
        hit = _classify_entry(entry, number, findings)
        if hit is not None:
            hits.append(hit)
    return hits


def _classify_entry(
    entry: object, line: int, findings: _Findings
) -> _Hit | None:
    payload = _get(entry, "payload")
    if not isinstance(payload, dict):
        return None
    kind = entry.get("type")
    if kind == "event_msg" and payload.get("type") == "item_completed":
        return _user_hit(entry, payload, line, findings)
    if (
        kind == "response_item"
        and payload.get("type") == "message"
        and payload.get("role") == "assistant"
    ):
        return _assistant_hit(entry, payload, line, findings)
    return None


def _user_hit(
    entry: dict, payload: dict, line: int, findings: _Findings
) -> _Hit | None:
    item = payload.get("item")
    item_type = _get(item, "type")
    if item_type == "UserMessage":
        text = _join_texts(item.get("content"), "text")
        if text is None:
            _suspect(findings, line, "payload.item.content")
            return None
        return _Hit(
            line,
            "user",
            text,
            payload.get("turn_id"),
            entry.get("ordinal"),
        )
    if isinstance(item_type, str) and "user" in item_type.lower():
        _suspect(findings, line, "payload.item.type")
    return None


def _assistant_hit(
    entry: dict, payload: dict, line: int, findings: _Findings
) -> _Hit | None:
    phase = payload.get("phase")
    if not isinstance(phase, str) or phase not in _KNOWN_PHASES:
        _suspect(findings, line, "payload.phase")
        return None
    if phase not in _PHASES:
        return None
    text = _join_texts(payload.get("content"), "output_text")
    if text is None:
        _suspect(findings, line, "payload.content")
        return None
    turn = _get(
        payload, "internal_chat_message_metadata_passthrough", "turn_id"
    )
    return _Hit(line, "assistant", text, turn, entry.get("ordinal"))


def _suspect(findings: _Findings, line: int, path: str) -> None:
    findings.add(
        "T5",
        "Eintrag sieht wie eine Nachricht aus, passt aber nicht",
        f"Zeile {line} {path}",
    )


def _get(value: object, *path: str) -> object:
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _join_texts(content: object, wanted_type: str) -> str | None:
    if not isinstance(content, list):
        return None
    parts = [
        part["text"]
        for part in content
        if isinstance(part, dict)
        and part.get("type") == wanted_type
        and isinstance(part.get("text"), str)
    ]
    return "\n".join(parts) if parts else None


def _ordered_messages(
    hits: list[_Hit], findings: _Findings
) -> tuple[TranscriptMessage, ...]:
    _check_counts(hits, findings)
    ordinals_ok = _check_ordinals(hits, findings)
    _check_texts(hits, findings)
    if not ordinals_ok:
        return ()
    ordered = sorted(hits, key=lambda h: (h.ordinal, h.line))
    _check_alternation_and_turns(ordered, findings)
    return tuple(
        TranscriptMessage(h.ordinal, h.role, h.text, h.line)
        for h in ordered
    )


def _check_counts(hits: list[_Hit], findings: _Findings) -> None:
    users = sum(h.role == "user" for h in hits)
    assistants = len(hits) - users
    if users == 0 or assistants == 0:
        findings.add(
            "T1",
            "Benutzer- und Assistentennachricht erforderlich",
            f"user={users}, assistant={assistants}",
        )
    elif users != assistants:
        findings.add(
            "T2",
            "Anzahl Benutzer- und Assistentennachrichten ungleich",
            f"user={users}, assistant={assistants}",
        )


def _valid_ordinal(value: object) -> bool:
    if type(value) is int:
        return True
    return type(value) is float and math.isfinite(value)


def _check_ordinals(hits: list[_Hit], findings: _Findings) -> bool:
    seen: dict[object, int] = {}
    for hit in hits:
        if not _valid_ordinal(hit.ordinal):
            findings.add(
                "T3",
                "ordinal fehlt oder ist nicht endlich numerisch",
                f"Zeile {hit.line} ordinal",
            )
        elif hit.ordinal in seen:
            findings.add(
                "T3",
                "ordinal doppelt",
                f"Zeilen {seen[hit.ordinal]} und {hit.line} ordinal",
            )
        else:
            seen[hit.ordinal] = hit.line
    return not findings.has("T3")


def _check_texts(hits: list[_Hit], findings: _Findings) -> None:
    for hit in hits:
        if not hit.text.strip():
            findings.add("T6", "leerer Text", f"Zeile {hit.line}")


def _check_alternation_and_turns(
    ordered: list[_Hit], findings: _Findings
) -> None:
    for index, hit in enumerate(ordered):
        expected = "user" if index % 2 == 0 else "assistant"
        if hit.role != expected:
            findings.add(
                "T4",
                "kein Wechsel Benutzer/Assistent (erster Bruch)",
                f"Position {index + 1}, Zeile {hit.line}",
            )
            return
    for user, assistant in zip(
        ordered[0::2], ordered[1::2], strict=False
    ):
        if user.turn and assistant.turn and user.turn != assistant.turn:
            findings.add(
                "T7",
                "turn_id von Benutzer und Assistent ungleich",
                f"Zeilen {user.line} und {assistant.line}",
            )


def _count(messages: tuple[TranscriptMessage, ...], role: str) -> int:
    return sum(m.role == role for m in messages)
