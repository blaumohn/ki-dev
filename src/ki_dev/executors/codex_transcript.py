"""Codex-Transkriptadapter: Dialog aus einer Sitzungs-JSONL lesen.

Fachliches Vorbild: ``mdman-ai-session/adapters/codex_transcript.py``.
Eingangsvertrag: Benutzer-``UserMessage`` und Assistenten-
``final_answer``. Die fruehere strenge Dialogannahme (cg1: strikter
Wechsel und gleiche Anzahl) ist abgeloest: wiederholte Rollen,
Nachtraege und offene Dialogenden sind gueltig; T1/T2/T4 erscheinen nur
als Zaehler in ``diagnostics``. T0 (keine Nachricht), T3, T5-T8 und
Strukturfehler bleiben Fehler und werden
ohne Reparatur gemeldet; ein CLI-Versionswechsel ist damit nicht
bewiesen. Diagnosen nennen nur Pruefcode, Zeile, Feldpfad und Zaehler
-- nie Gespraechsinhalte.
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
    decode_utf8,
    dialog_advisories,
    is_timestamp,
    line_count,
    parse_timestamp,
    validate_transcript,
)

AGENT = "codex"
PARSER_VERSION = "codex-dialog-2"
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
    lines = decode_utf8(data).split("\n")
    findings = _Findings()
    scan = _classify_lines(
        lines, data.endswith(b"\n"), session_id, findings
    )
    messages = _ordered_messages(scan.hits, findings)
    started_at = _started_at(scan.starts, findings)
    findings.raise_if_any()
    transcript = SessionTranscript(
        agent=AGENT,
        session_id=session_id,
        source_digest=digest,
        parser_version=PARSER_VERSION,
        started_at=started_at,
        last_activity_at=_last_activity(started_at, messages),
        messages=messages,
        diagnostics={
            "lines": line_count(data),
            "user_messages": _count(messages, "user"),
            "assistant_messages": _count(messages, "assistant"),
            **dialog_advisories([m.role for m in messages]),
        },
    )
    validate_transcript(transcript)
    return transcript


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


@dataclass(frozen=True)
class _Hit:
    line: int
    role: str
    text: str
    turn: object
    ordinal: object
    timestamp: str | None


@dataclass
class _Scan:
    hits: list[_Hit]
    # Belegte Startzeitpunkte aus session_meta dieser Sitzung.
    starts: list[tuple[int, str]]


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
    lines: list[str],
    ends_with_newline: bool,
    session_id: str,
    findings: _Findings,
) -> _Scan:
    scan = _Scan([], [])
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
        if _get(entry, "type") == "session_meta":
            _record_start(entry, number, session_id, scan, findings)
            continue
        hit = _classify_entry(entry, number, findings)
        if hit is not None:
            scan.hits.append(hit)
    return scan


def _record_start(
    entry: dict,
    line: int,
    session_id: str,
    scan: _Scan,
    findings: _Findings,
) -> None:
    # Nur session_meta mit passender id belegt den Start dieser Sitzung.
    if _get(entry, "payload", "id") != session_id:
        return
    stamp = _get(entry, "payload", "timestamp")
    if not is_timestamp(stamp):
        findings.add(
            "T8",
            "Zeitstempel fehlt oder ist ungueltig",
            f"Zeile {line} payload.timestamp",
        )
        return
    scan.starts.append((line, stamp))


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
            _message_timestamp(entry, line, findings),
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
    return _Hit(
        line,
        "assistant",
        text,
        turn,
        entry.get("ordinal"),
        _message_timestamp(entry, line, findings),
    )


def _message_timestamp(
    entry: dict, line: int, findings: _Findings
) -> str | None:
    """Fehlt der Zeitstempel, bleibt er fehlend; ein vorhandener
    ungueltiger Wert ist ein Fehler."""
    if "timestamp" not in entry:
        return None
    stamp = entry["timestamp"]
    if not is_timestamp(stamp):
        findings.add(
            "T8",
            "Zeitstempel fehlt oder ist ungueltig",
            f"Zeile {line} timestamp",
        )
        return None
    return stamp


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
    _check_not_empty(hits, findings)
    ordinals_ok = _check_ordinals(hits, findings)
    _check_texts(hits, findings)
    if not ordinals_ok:
        return ()
    ordered = sorted(hits, key=lambda h: (h.ordinal, h.line))
    _check_turns(ordered, findings)
    return tuple(
        TranscriptMessage(
            ordinal=h.ordinal,
            role=h.role,
            text=h.text,
            source_line=h.line,
            position=position,
            timestamp=h.timestamp,
        )
        for position, h in enumerate(ordered, 1)
    )


def _check_not_empty(hits: list[_Hit], findings: _Findings) -> None:
    # T1/T2 sind nur Zaehler (dialog_advisories); ohne jede Nachricht
    # ist das Transkript aber kein Erfolg.
    if not hits:
        findings.add(
            "T0",
            "keine Dialognachrichten gefunden",
            "user=0, assistant=0",
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


def _check_turns(ordered: list[_Hit], findings: _Findings) -> None:
    # Turn-Paare sind nur bei sauberem Wechsel zuordenbar (wie T7 im
    # Vorbild); T4 selbst ist nur ein Zaehler.
    roles = [hit.role for hit in ordered]
    if dialog_advisories(roles)["T4_role_breaks"]:
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


def _started_at(
    starts: list[tuple[int, str]], findings: _Findings
) -> str | None:
    if len({parse_timestamp(stamp) for _, stamp in starts}) > 1:
        findings.add(
            "T8",
            "session_meta nennt widerspruechliche Startzeiten",
            "Zeilen " + ", ".join(str(line) for line, _ in starts),
        )
        return None
    return starts[0][1] if starts else None


def _last_activity(
    started_at: str | None, messages: tuple[TranscriptMessage, ...]
) -> str | None:
    stamps = [m.timestamp for m in messages if m.timestamp is not None]
    if started_at is not None:
        stamps.append(started_at)
    return max(stamps, key=parse_timestamp, default=None)


def _count(messages: tuple[TranscriptMessage, ...], role: str) -> int:
    return sum(m.role == role for m in messages)
