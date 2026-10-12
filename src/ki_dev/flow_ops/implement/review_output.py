"""Formale Ausgabe der Review-Rolle des Ablaufs implement: Laufhülle
(``run_id``, ``round_id``) prüfen, dann den gemeinsamen Urteilskern
aus :mod:`ki_dev.review_decision`, und das Urteil an den Auftrag
binden."""

from __future__ import annotations

from dataclasses import dataclass

from ki_dev.adapter.contract import ReviewVocabulary, RunTask
from ki_dev.flow.model import Verdict
from ki_dev.flow_ops.implement.machine import IMPLEMENT
from ki_dev.review_decision import (
    ReviewContractError,
    bind_requirement,
    load_json_object,
    parse_verdict,
)
from ki_dev.runner.review_output import AgentProtocolError

# Review-Antworten des Umsetzungsablaufs, einmal aus dem Ablauf gebildet
# und dem Adapter mitgegeben (Adapter kennen keinen Ablauf).
REVIEW_VOCABULARY = ReviewVocabulary(
    events=IMPLEMENT.review_events(),
    changes=IMPLEMENT.events_with(Verdict.CHANGES)[0],
    unbound=IMPLEMENT.unbound_changes_event(),
    texts={
        name: item.text
        for name, item in IMPLEMENT.finding_classes.items()
    },
)



@dataclass(frozen=True)
class ReviewDecision:
    run_id: str
    round_id: int
    event: str
    detail: str = ""
    requirement_ref: str | None = None


def parse_review_decision(
    raw: str, *, run_id: str, round_id: int
) -> ReviewDecision:
    """Laufhülle (run_id, round_id) prüfen, dann den gemeinsamen Kern
    aus review_decision; Vertragsfehler werden AgentProtocolError."""
    try:
        value = load_json_object(raw)
        _check_identity(value, run_id, round_id)
        core = {k: v for k, v in value.items() if k not in _IDENTITY}
        verdict = parse_verdict(core, IMPLEMENT)
    except ReviewContractError as exc:
        raise AgentProtocolError(str(exc)) from exc
    return ReviewDecision(
        run_id,
        round_id,
        verdict.event,
        verdict.detail,
        verdict.requirement_ref,
    )


_IDENTITY = ("run_id", "round_id")


def _check_identity(value: dict, run_id: str, round_id: int) -> None:
    if any(key not in value for key in _IDENTITY):
        raise ReviewContractError(
            "Review-Ausgabe hat nicht exakt die erwarteten Felder"
        )
    received_round = value["round_id"]
    if (
        value["run_id"] != run_id
        or isinstance(received_round, bool)
        or not isinstance(received_round, int)
        or received_round != round_id
    ):
        raise ReviewContractError(
            "Review-Ausgabe gehoert zu fremdem Lauf oder fremder Runde"
        )


def bind_review_decision(
    decision: ReviewDecision, task: RunTask
) -> ReviewDecision:
    """CHANGES an ein Abnahmekriterium des Laufs binden (gemeinsame
    Regel ``bind_requirement``)."""
    return bind_requirement(
        decision, task.acceptance_criterion_refs(), IMPLEMENT
    )
