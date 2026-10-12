"""Formale Antwort auf eine Übergabe lesen und an den Auftrag binden.

Der Ausführer prüft die Hülle und den gemeinsamen Urteilskern aus
:mod:`ki_dev.review_decision`; erst das geprüfte Urteil wird zum
Ereignis des Ablaufs. Freitext ist nie unmittelbar ein Ereignis. Die
Hülle trägt die Kennung des Versuchs (``attempt``), für den die
Übergabe ausgegeben wurde; ob sie zum wartenden Versuch passt, prüft
der Ausführer beim Fortsetzen. Die Laufhülle von implement
(``run_id``, ``round_id``) liegt im Paket
(:mod:`ki_dev.flow_ops.implement.review_output`).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field

from ki_dev.flow.model import Flow
from ki_dev.review_decision import (
    CORE_FIELDS,
    ReviewContractError,
    ReviewVerdict,
    bind_requirement,
    load_json_object,
    parse_verdict,
)


class AgentProtocolError(ValueError):
    """Agentenausgabe verletzt Hülle oder Referenzbindung."""


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
