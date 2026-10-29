"""Claude-Transkriptadapter: Dialog aus einer Sitzungs-JSONL lesen.

Fachliches Vorbild: ``mdman-ai-session/adapters/claude_transcript.py``
und ``docs/transkript-pruefungen.md``. Uebernommen werden menschliche
Eingaben und ``end_turn``-Textbloecke. Technische Aufgabenmeldungen
werden nur bei belegter Herkunft (``origin.kind``, ``turnOrigin``,
``promptSource`` und String-Inhalt) ausgelassen und gezaehlt,
Slash-Befehlszeilen nur ohne jede Herkunftsangabe; ein XML-Tag allein
belegt nichts, menschliche Zitate bleiben. Zeitstempel sind optional;
``sessionId`` muss der angeforderten Sitzung entsprechen. Wiederholte
Rollen und offene Eingaben
sind gueltig und werden gezaehlt. Unbekannte Herkunft, ungueltiges JSON
und leere Transkripte sind Fehler. Claude kennt keine Quellordinals;
``ordinal`` bleibt ``None``. Keine Rekonstruktion von Resume-/Fork-
Zweigen. Diagnosen nennen nur Zeile, Feldpfad, Regel, bekannte
Kennzeichen und Zaehler -- nie Gespraechsinhalte.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

from .claude_sessions import (
    find_claude_sessions,
    resolve_claude_sessions_dir,
    validate_claude_session_id,
)
from .claude_transcript_content import classify_content
from .claude_transcript_schema import (
    ENVELOPE,
    MESSAGE,
    line_error,
    validate_record,
)
from .session_config import session_environ
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

AGENT = "claude"
PARSER_VERSION = "claude-dialog-1"

def read_claude_session(session_id: str) -> SessionTranscript:
    """Ein-/Ausgabegrenze: Umgebung und Datei nur hier gelesen.

    Erwartete Konfigurations- und Dateifehler werden zu bereinigten
    ``TranscriptError``; Ausnahmetexte des Betriebssystems (Pfade)
    gelangen nicht in die Meldung.
    """
    validate_claude_session_id(session_id)
    try:
        root = resolve_claude_sessions_dir(
            session_environ(os.environ), Path.home()
        )
    except ValueError as exc:
        raise TranscriptError(
            (f"Claude-Sitzungsordner nicht bestimmbar: {exc}",)
        ) from None
    except RuntimeError:
        raise TranscriptError(
            (
                "Claude-Sitzungsordner nicht bestimmbar: "
                "Home-Verzeichnis unbekannt",
            )
        ) from None
    try:
        data = _single_session(root, session_id).read_bytes()
    except OSError as exc:
        raise TranscriptError(
            (f"Claude-Sitzung nicht lesbar ({type(exc).__name__})",)
        ) from None
    return transcript_from_bytes(session_id, data)


def transcript_from_bytes(
    session_id: str, data: bytes
) -> SessionTranscript:
    """Reine Extraktion aus genau den Bytes, ueber die der Hash geht."""
    digest = hashlib.sha256(data).hexdigest()
    lines = decode_utf8(data).split("\n")
    stats: Counter[str] = Counter()
    rows, stamps = _extract(
        lines, data.endswith(b"\n"), session_id, stats
    )
    messages = tuple(
        TranscriptMessage(
            ordinal=None,
            role=role,
            text=text,
            source_line=line,
            position=position,
            timestamp=stamp,
        )
        for position, (line, role, text, stamp) in enumerate(rows, 1)
    )
    transcript = SessionTranscript(
        agent=AGENT,
        session_id=session_id,
        source_digest=digest,
        parser_version=PARSER_VERSION,
        started_at=min(stamps, key=parse_timestamp, default=None),
        last_activity_at=max(stamps, key=parse_timestamp, default=None),
        messages=messages,
        diagnostics={
            "lines": line_count(data),
            "user_messages": sum(m.role == "user" for m in messages),
            "assistant_messages": sum(
                m.role == "assistant" for m in messages
            ),
            **dialog_advisories([m.role for m in messages]),
            **stats,
        },
    )
    validate_transcript(transcript)
    return transcript


def _single_session(root: Path, session_id: str) -> Path:
    if not root.is_dir():
        raise TranscriptError(
            ("Claude-Sitzungsordner existiert nicht",)
        )
    found = find_claude_sessions(root, session_id)
    if not found:
        raise TranscriptError(("Claude-Sitzung nicht gefunden",))
    if len(found) > 1:
        raise TranscriptError(
            (f"Claude-Sitzung mehrdeutig ({len(found)} Treffer)",)
        )
    return found[0]


def _extract(
    lines: list[str],
    ends_with_newline: bool,
    session_id: str,
    stats: Counter[str],
) -> tuple[list[tuple[int, str, str, str | None]], list[str]]:
    """Dialogzeilen und vorhandene Zeitstempel der Sitzungsbeitraege.

    Die Zeitstempel stammen aus den Beitraegen der Sitzung selbst
    (``timestamp`` je user-/assistant-Eintrag), nie aus Datei- oder
    Exportdaten. Ein fehlender Zeitstempel bleibt fehlend.
    """
    rows, stamps = [], []
    pending = False
    for number, entry in _message_records(
        lines, ends_with_newline, session_id, stats
    ):
        if "timestamp" in entry:
            stamps.append(entry["timestamp"])
        else:
            stats["records_without_timestamp"] += 1
        result = classify_content(entry, number, stats)
        if result is not None:
            pending = _record_dialog(
                rows, number, entry, result, stats, pending
            )
    stats["human_input_pending_at_eof"] = int(pending)
    if not rows:
        raise TranscriptError(("keine Transkriptbeitraege gefunden",))
    return rows, stamps


def _message_records(
    lines: list[str],
    ends_with_newline: bool,
    session_id: str,
    stats: Counter[str],
) -> Iterator[tuple[int, dict]]:
    seen: set[str] = set()
    parents: list[str] = []
    for number, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        entry = _parse(
            raw, number, number == len(lines), ends_with_newline
        )
        validate_record(ENVELOPE, entry, number)
        stats["records"] += 1
        _check_lineage(entry, number, seen, parents)
        if entry["type"] not in {"user", "assistant"}:
            continue
        validate_record(MESSAGE, entry, number)
        _check_message(entry, number, session_id)
        yield number, entry
    stats["branch_points"] = sum(
        n > 1 for n in Counter(parents).values()
    )


def _record_dialog(
    rows: list[tuple[int, str, str, str | None]],
    number: int,
    entry: dict,
    result: tuple[str, str, str],
    stats: Counter[str],
    pending: bool,
) -> bool:
    role, text, phase = result
    if not text.strip():
        raise line_error(number, "leerer Transkripttext")
    if role == "user":
        if pending:
            stats["human_inputs_without_final_before_next_input"] += 1
        pending = True
    elif phase == "final":
        pending = False
    if role == "assistant":
        stats[f"{phase}_text_records"] += 1
        if phase != "final":
            return pending
    rows.append((number, role, text, entry.get("timestamp")))
    return pending


def _parse(raw: str, number: int, last: bool, ends_with_newline: bool):
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        partial = last and not ends_with_newline
        raise line_error(
            number,
            "ungueltiges JSON"
            + (
                " (letzte Zeile, evtl. unvollstaendig)"
                if partial
                else ""
            ),
        ) from None


def _check_lineage(
    entry: dict, number: int, seen: set[str], parents: list[str]
) -> None:
    if "uuid" not in entry:
        return
    if entry["uuid"] in seen:
        raise line_error(number, "doppelte uuid")
    parent = entry.get("parentUuid")
    if parent is not None and parent not in seen:
        raise line_error(
            number, "parentUuid fehlt oder steht nicht davor"
        )
    seen.add(entry["uuid"])
    if parent is not None:
        parents.append(parent)


def _check_message(entry: dict, number: int, session_id: str) -> None:
    # Deckt auch gemischte Sitzungen ab; der Wert bleibt ungenannt.
    if entry["sessionId"] != session_id:
        raise line_error(
            number, "sessionId passt nicht zur angeforderten Sitzung"
        )
    if entry["message"]["role"] != entry["type"]:
        raise line_error(
            number, "type und message.role widersprechen sich"
        )
    if "timestamp" in entry and not is_timestamp(entry["timestamp"]):
        raise line_error(number, "ungueltiges Feld timestamp (Datum)")
