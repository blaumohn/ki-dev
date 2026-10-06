"""handoff map: Codex- oder Claude-Sitzung als Quellen-Bead uebergeben.

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
from ki_dev.handoff import (
    Step,
    render_base_handoff,
    render_guideline_block,
)
from ki_dev.handoff_guidelines import GuidelineSection
from ki_dev.handoff_source import (
    HandoffSourceError,
    source_key,
    store_source,
)
from ki_dev.step_flow import StepFlow

_READING_HINT = (
    "Quelle: normalisiertes Transkript, eine Nachricht je Zeile "
    "(position, ordinal, role, text, source_line, timestamp). "
    "Abschnittsweise lesen und Fundstellen über source_line angeben; "
    "ordinal ist die Herkunftsnummer und kann fehlen (null). "
    "Wiederholte Rollen und offene Eingaben sind gültig. "
    "Wiederholungen, Präzisierungen und Widersprüche gehören in die "
    "Karte; die Quelle wurde nicht inhaltlich bereinigt."
)


def map_handoff(
    agent: str,
    session_id: str,
    workdir: Path,
    guidelines: tuple[GuidelineSection, ...],
    base_max_chars: int,
    flow: StepFlow,
) -> str:
    """Kurzer map-Auftrag; schreibt Quellen-Datei und -Bead.

    ``guidelines``, ``base_max_chars`` und ``flow`` sind bereits geladen
    und geprüft, damit Quellenfehler vor jeder Schreibwirkung auffallen.
    Die Basis (mit Lesehinweis) lässt sich erst nach der Quellenanlage
    prüfen; bei Übergröße bleiben Quelle und Bead bestehen.
    """
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
    base = render_base_handoff(
        issue,
        Step.MAP,
        flow=flow,
        reading_hint=_READING_HINT,
        max_chars=base_max_chars,
    )
    return base + render_guideline_block(guidelines)


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
