"""handoff map: Codex- oder Claude-Sitzung als Quellen-Bead uebergeben.

Ablauf: Adapter lesen/pruefen -> normalisierte Quelle speichern ->
Quellen-Bead finden/anlegen -> bestehende map-Uebergabe rendern
(``hand_over``). Das Rendering bleibt frei von Beads-Schreib-I/O.
"""

from __future__ import annotations

from pathlib import Path

from ki_dev.adapter.executors.session_transcript import (
    SessionTranscript,
)
from ki_dev.adapter.executors.transcript import read_session_transcript
from ki_dev.flow.review_flow import TEMPLATES, ReviewFlow
from ki_dev.flow.templates import render, text
from ki_dev.ops.context.beads_reader import read_issue
from ki_dev.ops.context.blocks import TurnInput, state_turn
from ki_dev.ops.context.contract import Step
from ki_dev.ops.context.guidelines import GuidelineSection
from ki_dev.step.beads_source import (
    SourceBead,
    ensure_source_bead,
    short_session_reference,
)
from ki_dev.step.source import (
    HandoffSourceError,
    accepted_refs,
    source_key,
    store_source,
)
from ki_dev.step.turn import hand_over, require_valid


def map_handoff(
    agent: str,
    session_id: str,
    title: str,
    workdir: Path,
    guidelines: tuple[GuidelineSection, ...],
    base_max_chars: int,
    flow: ReviewFlow,
) -> str:
    """Kurzer map-Auftrag; schreibt Snapshot und Quellen-Bead.

    ``guidelines``, ``base_max_chars`` und ``flow`` sind bereits geladen
    und geprüft, damit Quellenfehler vor jeder Schreibwirkung auffallen.
    Die Basis (mit Lesehinweis) lässt sich erst nach der Quellenanlage
    prüfen; bei Übergröße bleiben Quelle und Bead bestehen.
    """
    transcript = read_session_transcript(agent, session_id)
    stored = store_source(transcript, title, workdir)
    session_ref = short_session_reference(
        transcript.session_id, workdir
    )
    bead_id = ensure_source_bead(
        _source_bead(transcript, stored.as_posix(), session_ref),
        workdir,
    )
    issue = read_issue(bead_id, workdir)
    refs = issue.source_refs
    if not isinstance(refs, list):
        refs = []
    if not set(refs) & set(accepted_refs(transcript, stored, workdir)):
        raise HandoffSourceError(
            "Quellen-Bead verweist nicht auf das lokale Artefakt"
        )
    require_valid(issue, Step.MAP, None)
    state = flow.flow.start
    subject = TurnInput(
        issue,
        flow,
        state,
        guidelines=guidelines,
        reading_hint=text(TEMPLATES, "map-reading-hint"),
    )
    return hand_over(
        flow, state_turn(flow, state), subject, base_max_chars
    )


def _source_bead(
    transcript: SessionTranscript, relative: str, session_ref: str
) -> SourceBead:
    values = {
        "agent": transcript.agent,
        "session_ref": session_ref,
    }
    return SourceBead(
        key=source_key(transcript),
        title=render(TEMPLATES, "source-bead-title", **values),
        description=render(
            TEMPLATES,
            "source-bead",
            **values,
            digest=transcript.source_digest,
            parser=transcript.parser_version,
            count=len(transcript.messages),
            path=relative,
        ),
        source_ref=relative,
    )
