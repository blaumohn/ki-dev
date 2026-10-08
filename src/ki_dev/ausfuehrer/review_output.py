"""Formale Ausgabe der Review-Rolle lesen und an den Auftrag binden.

Der Ausführer prüft die Hülle (``run_id``, ``round_id``) und den
gemeinsamen Urteilskern aus :mod:`ki_dev.review_decision`; erst das
geprüfte Urteil wird zum Ereignis des Ablaufs. Freitext ist nie
unmittelbar ein Ereignis.
"""

from __future__ import annotations

from dataclasses import dataclass

from ki_dev.adapter.contract import RunTask
from ki_dev.review_decision import (
    RUN_ACTIONS,
    ReviewAction,
    ReviewContractError,
    bind_requirement,
    load_json_object,
    parse_verdict,
)


class AgentProtocolError(ValueError):
    """Agentenausgabe verletzt Hülle oder Referenzbindung."""


@dataclass(frozen=True)
class ReviewDecision:
    run_id: str
    round_id: int
    action: ReviewAction
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
        verdict = parse_verdict(core, RUN_ACTIONS)
    except ReviewContractError as exc:
        raise AgentProtocolError(str(exc)) from exc
    return ReviewDecision(
        run_id,
        round_id,
        verdict.action,
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
    return bind_requirement(decision, task.acceptance_criterion_refs())
