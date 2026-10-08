"""handoff map: Codex- oder Claude-Sitzung als Quellen-Bead uebergeben.

Ablauf: Adapter lesen/pruefen -> normalisierte Quelle speichern ->
Quellen-Bead finden/anlegen -> bestehende map-Uebergabe rendern. Der
reine Handoff-Kern (``handoff.py``) bleibt frei von Beads-Schreib-I/O.
"""

from __future__ import annotations

from pathlib import Path

from ki_dev.adapter.executors.session_transcript import (
    SessionTranscript,
)
from ki_dev.adapter.executors.transcript import read_session_transcript
from ki_dev.flow.planning import NAME, PlanningFlow
from ki_dev.flow.templates import text
from ki_dev.step.beads_reader import read_issue
from ki_dev.step.beads_source import SourceBead, ensure_source_bead
from ki_dev.step.contract import Step
from ki_dev.step.guidelines import (
    GuidelineSection,
    render_guideline_block,
)
from ki_dev.step.handoff import render_base_handoff
from ki_dev.step.source import (
    HandoffSourceError,
    accepted_refs,
    source_key,
    store_source,
)


def map_handoff(
    agent: str,
    session_id: str,
    title: str,
    workdir: Path,
    guidelines: tuple[GuidelineSection, ...],
    base_max_chars: int,
    flow: PlanningFlow,
) -> str:
    """Kurzer map-Auftrag; schreibt Snapshot und Quellen-Bead.

    ``guidelines``, ``base_max_chars`` und ``flow`` sind bereits geladen
    und geprüft, damit Quellenfehler vor jeder Schreibwirkung auffallen.
    Die Basis (mit Lesehinweis) lässt sich erst nach der Quellenanlage
    prüfen; bei Übergröße bleiben Quelle und Bead bestehen.
    """
    transcript = read_session_transcript(agent, session_id)
    stored = store_source(transcript, title, workdir)
    bead_id = ensure_source_bead(
        _source_bead(transcript, stored.as_posix()), workdir
    )
    issue = read_issue(bead_id, workdir)
    refs = issue.source_refs
    if not isinstance(refs, list):
        refs = []
    if not set(refs) & set(accepted_refs(transcript, stored, workdir)):
        raise HandoffSourceError(
            "Quellen-Bead verweist nicht auf das lokale Artefakt"
        )
    base = render_base_handoff(
        issue,
        Step.MAP,
        flow=flow,
        reading_hint=text(NAME, "map-reading-hint"),
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
            f"{relative}. Kopfzeile, danach eine Nachricht je Zeile; "
            "keine "
            "Gesprächsinhalte in Beads. Quelle für den Schritt "
            "map; ersetzt keine Karte."
        ),
        source_ref=relative,
    )
