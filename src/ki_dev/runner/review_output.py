"""Formale Ausgabe der Review-Rolle lesen und an den Auftrag binden.

Der Ausführer prüft die Hülle und den gemeinsamen Urteilskern aus
:mod:`ki_dev.review_decision`; erst das geprüfte Urteil wird zum
Ereignis des Ablaufs. Freitext ist nie unmittelbar ein Ereignis. Die
Hülle des Umsetzungsablaufs trägt ``run_id`` und ``round_id``, die des
Planungsablaufs die Kennung des Versuchs (``attempt``), für den die
Übergabe ausgegeben wurde; ob sie zum wartenden Versuch passt, prüft
der Ausführer beim Fortsetzen.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field

from ki_dev.adapter.contract import ReviewVocabulary, RunTask
from ki_dev.flow.model import Flow, Verdict
from ki_dev.review_decision import (
    CORE_FIELDS,
    ReviewContractError,
    ReviewVerdict,
    bind_requirement,
    load_json_object,
    parse_verdict,
)
from ki_dev.runner.machine import IMPLEMENT

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


class AgentProtocolError(ValueError):
    """Agentenausgabe verletzt Hülle oder Referenzbindung."""


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


@dataclass(frozen=True)
class PlanningAnswer:
    """Geprüfte Antwort des Planungsablaufs: das an die Abnahmekriterien
    gebundene Urteil, die Kennung des Versuchs und die zusätzlichen
    (geprüften) Felder."""

    verdict: ReviewVerdict
    attempt: str
    extras: Mapping[str, object] = field(default_factory=dict)


ANSWER_ATTEMPT = "attempt"


def parse_planning_answer(
    raw: str,
    flow: Flow,
    refs: Collection[str],
    extra_properties: Mapping[str, dict],
    check: Callable[[ReviewVerdict, Mapping[str, object]], None],
) -> PlanningAnswer:
    """Hülle (``attempt``) prüfen, dann den gemeinsamen Kern aus
    review_decision samt optionaler Felder (``extra_properties``);
    ``check`` prüft Urteil und Zusatzfelder gegen die Außenwelt des
    Aufrufers. Danach wird CHANGES an die Abnahmekriterien ``refs``
    gebunden. Vertragsfehler werden AgentProtocolError."""
    try:
        value = load_json_object(raw)
        attempt = _attempt(value)
        core = {k: v for k, v in value.items() if k != ANSWER_ATTEMPT}
        verdict = parse_verdict(core, flow, extra_properties)
        extras = {k: v for k, v in core.items() if k not in CORE_FIELDS}
        check(verdict, extras)
    except ReviewContractError as exc:
        raise AgentProtocolError(str(exc)) from exc
    return PlanningAnswer(
        bind_requirement(verdict, refs, flow), attempt, extras
    )


def _attempt(value: dict) -> str:
    if ANSWER_ATTEMPT not in value:
        raise ReviewContractError(f"{ANSWER_ATTEMPT}: fehlt")
    attempt = value[ANSWER_ATTEMPT]
    if not isinstance(attempt, str) or not attempt.strip():
        raise ReviewContractError(
            f"{ANSWER_ATTEMPT}: muss nichtleerer Text sein"
        )
    return attempt
