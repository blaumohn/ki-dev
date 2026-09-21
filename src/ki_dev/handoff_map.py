"""handoff map: Codex-Sitzung als Quellen-Bead uebergeben.

Ablauf: Adapter lesen/pruefen -> normalisierte Quelle speichern ->
Quellen-Bead finden/anlegen -> bestehende map-Uebergabe rendern. Der
reine Handoff-Kern (``handoff.py``) bleibt frei von Beads-Schreib-I/O.
"""

from __future__ import annotations

from pathlib import Path

from ki_dev.beads_reader import read_issue
from ki_dev.beads_source import SourceBead, ensure_source_bead
from ki_dev.executors.session_transcript import SessionTranscript
from ki_dev.executors.transcript import read_session_transcript
from ki_dev.handoff import Step, render_handoff
from ki_dev.handoff_source import (
    HandoffSourceError,
    source_key,
    store_source,
)

_READING_HINT = (
    "Quelle: normalisiertes Transkript, eine Nachricht je Zeile "
    "(ordinal, role, text, source_line). Abschnittsweise lesen und "
    "Fundstellen über source_line/ordinal angeben. Wiederholungen, "
    "Präzisierungen und Widersprüche gehören in die Karte; die "
    "Quelle wurde nicht inhaltlich bereinigt."
)


def map_handoff(agent: str, session_id: str, workdir: Path) -> str:
    """Kurzer map-Auftrag; schreibt Quellen-Datei und -Bead."""
    transcript = read_session_transcript(agent, session_id)
    relative = store_source(transcript, workdir).as_posix()
    bead_id = ensure_source_bead(
        _source_bead(transcript, relative), workdir
    )
    issue = read_issue(bead_id, workdir)
    if not isinstance(issue.source_refs, list) or (
        relative not in issue.source_refs
    ):
        raise HandoffSourceError(
            "Quellen-Bead verweist nicht auf das lokale Artefakt"
        )
    return f"{render_handoff(issue, Step.MAP)}\n{_READING_HINT}\n"


def _source_bead(
    transcript: SessionTranscript, relative: str
) -> SourceBead:
    agent, sid = transcript.agent, transcript.session_id
    return SourceBead(
        key=source_key(transcript),
        title=f"Quelle: {agent}-Sitzung {sid}",
        description=(
            f"Normalisiertes Transkript der {agent}-Sitzung {sid} "
            f"(Stand {transcript.source_digest}, "
            f"Parser {transcript.parser_version}, "
            f"{len(transcript.messages)} Nachrichten) unter "
            f"{relative}. Eine Nachricht je Zeile; keine "
            "Gesprächsinhalte in Beads. Quelle für den Schritt "
            "map; ersetzt keine Karte."
        ),
        source_ref=relative,
    )
