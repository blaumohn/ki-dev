"""Formale Antwort auf eine Übergabe lesen und an den Auftrag binden.

Der Aufrufer prüft den gemeinsamen Urteilskern aus
:mod:`ki_dev.review_decision`; erst das geprüfte Urteil wird zum
Ereignis des Ablaufs. Freitext ist nie unmittelbar ein Ereignis. Die
Laufhülle von implement
(``run_id``, ``round_id``) liegt im Paket
(:mod:`ki_dev.flow_ops.implement.review_output`).
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field

from ki_dev.adapter.contract import (
    AgentProtocolError as AgentProtocolError,
)
from ki_dev.flow.model import Flow
from ki_dev.review_decision import (
    CORE_FIELDS,
    ReviewContractError,
    ReviewVerdict,
    bind_requirement,
    load_json_object,
    parse_verdict,
)


@dataclass(frozen=True)
class PlanningAnswer:
    """Geprüfte Antwort des Planungsablaufs: das an die Abnahmekriterien
    gebundene Urteil und die zusätzlichen (geprüften) Felder."""

    verdict: ReviewVerdict
    extras: Mapping[str, object] = field(default_factory=dict)


def parse_planning_answer(
    raw: str,
    flow: Flow,
    refs: Collection[str],
    extra_properties: Mapping[str, dict],
    check: Callable[[ReviewVerdict, Mapping[str, object]], None],
) -> PlanningAnswer:
    """Den gemeinsamen Kern aus review_decision samt optionaler Felder
    (``extra_properties``) prüfen;
    ``check`` prüft Urteil und Zusatzfelder gegen die Außenwelt des
    Aufrufers. Danach wird CHANGES an die Abnahmekriterien ``refs``
    gebunden. Vertragsfehler werden AgentProtocolError."""
    try:
        value = load_json_object(raw)
        verdict = parse_verdict(value, flow, extra_properties)
        extras = {
            k: v for k, v in value.items() if k not in CORE_FIELDS
        }
        check(verdict, extras)
    except ReviewContractError as exc:
        raise AgentProtocolError(str(exc)) from exc
    return PlanningAnswer(bind_requirement(verdict, refs, flow), extras)
