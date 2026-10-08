"""--decision-file: Reviewer-Antwort lesen, nächste Nachricht wählen.

Datenfluss: Die Umsetzungs-Review endet mit genau einem JSON-Objekt im
gemeinsamen Vertrag (review_decision): ``event`` ist ein
Review-Ereignis des Planungsablaufs. Der Mensch gibt es mit
``ki-dev step BEAD_ID --step review --next-turn --decision-file
DATEI|-`` weiter. step prüft es, bindet ``fix`` an ein
Abnahmekriterium des Beads (sonst ``decision`` wie im Lieferablauf)
und gibt die Nachricht für den Empfänger aus, den der Planungsablauf
für ``implement.review`` und dieses Ereignis nennt. Kein Vorlauf, keine
Schreibwirkung, kein Agentenstart.

Begrenzte Prüfsteuerung (5we): Die Antwort darf optional
``preflight_args`` {NAME: ARGS} und ``preflight_skip`` {NAME: GRUND}
enthalten, nie bei PASS. step prüft sie mit denselben Parsern wie die
CLI-Optionen gegen die Vorlauf-Konfiguration und zeigt den fertigen
Befehl; ausgeführt wird er nur vom Menschen.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import BinaryIO

from ki_dev.flow.model import PASS, Verdict
from ki_dev.flow.planning import PlanningFlow
from ki_dev.review_decision import (
    ReviewContractError,
    ReviewVerdict,
    bind_requirement,
    load_json_object,
    parse_verdict,
)
from ki_dev.step.contract import one_line
from ki_dev.step.handoff import HandoffIssue, criteria_with_refs
from ki_dev.step.next_turn import read_bounded_text
from ki_dev.step.preflight import PreflightConfig
from ki_dev.step.preflight_options import (
    ARGS_OPTION,
    SKIP_OPTION,
    PreflightOptionError,
    apply_preflight_options,
    parse_preflight_args,
    parse_preflight_skip,
)

# Obergrenze der eingelesenen Antwort (Zeichen); nie gekürzt.
DECISION_MAX_CHARS = 20000
_REVIEW_STATE = "implement.review"
_WHAT = "Review-Antwort"


_TEXT_MAP = {
    "type": "object",
    "additionalProperties": {"type": "string"},
}
# Optionale Steuerfelder der step-Variante; Werte prüft danach
# preflight_options (eine Regel für CLI und Antwort).
_CONTROL_SCHEMA = {
    "preflight_args": _TEXT_MAP,
    "preflight_skip": _TEXT_MAP,
}


class DecisionInputError(ValueError):
    """Antwort ungültig oder zu lang (Exit 2), ohne Rohwerte."""


@dataclass(frozen=True)
class StepDecision:
    """Gebundenes Urteil plus vorgeschlagene Prüfsteuerung."""

    verdict: ReviewVerdict
    preflight_args: dict[str, str] = field(default_factory=dict)
    preflight_skip: dict[str, str] = field(default_factory=dict)


def read_decision(source: str, stdin: Callable[[], BinaryIO]) -> str:
    text = read_bounded_text(source, DECISION_MAX_CHARS, stdin, _WHAT)
    if len(text) > DECISION_MAX_CHARS:
        raise DecisionInputError(
            f"{_WHAT} überschreitet {DECISION_MAX_CHARS} Zeichen; "
            "keine Kürzung"
        )
    return text


def parse_step_decision(
    raw: str,
    issue: HandoffIssue,
    load_config: Callable[[], PreflightConfig],
    *,
    flow: PlanningFlow,
) -> StepDecision:
    """Vertrag prüfen, an die Abnahmekriterien binden, Steuerung prüfen.

    ``load_config`` liefert die Vorlauf-Konfiguration und wird nur bei
    Steuerfeldern aufgerufen; ihre Fehler gibt es unverändert weiter.
    """
    try:
        value = load_json_object(raw)
        verdict = parse_verdict(value, flow.flow, _CONTROL_SCHEMA)
        args = dict(value.get("preflight_args", {}))
        skip = dict(value.get("preflight_skip", {}))
        _check_control(verdict, args, skip, load_config)
    except (ReviewContractError, PreflightOptionError) as exc:
        raise DecisionInputError(f"{_WHAT} ungültig: {exc}") from exc
    refs = [ref for ref, _ in criteria_with_refs(issue)]
    return StepDecision(
        bind_requirement(verdict, refs, flow.flow), args, skip
    )


def _check_control(
    verdict: ReviewVerdict,
    args: dict[str, str],
    skip: dict[str, str],
    load_config: Callable[[], PreflightConfig],
) -> None:
    """PASS braucht Volllauf; Werte wie die CLI-Optionen prüfen."""
    if not (args or skip):
        return
    if verdict.event == PASS:
        raise ReviewContractError(
            "preflight_args/preflight_skip: bei PASS nicht erlaubt"
        )
    apply_preflight_options(
        load_config(),
        parse_preflight_args(_pairs(args)),
        parse_preflight_skip(_pairs(skip)),
    )


def _pairs(values: dict[str, str]) -> list[str]:
    return [f"{name}={text}" for name, text in values.items()]


def render_decision_turn(
    issue: HandoffIssue, decision: StepDecision, *, flow: PlanningFlow
) -> str:
    """Nachricht an den Empfänger laut Zustandstabelle."""
    verdict = decision.verdict
    judgement = flow.flow.verdict(verdict.event)
    bead = one_line(issue.id)
    lines = [
        f"Empfänger: {_recipient(judgement)}",
        f"Bead: {bead} - {one_line(issue.title)}",
        "",
        *_body(verdict, judgement),
        "",
        *flow.hint_lines(_REVIEW_STATE, bead, (verdict.event,)),
        *_control_lines(decision, bead),
    ]
    return "\n".join(lines) + "\n"


def _control_lines(decision: StepDecision, bead: str) -> list[str]:
    """Vorgeschlagene Prüfsteuerung als ausführbarer Befehl."""
    if not (decision.preflight_args or decision.preflight_skip):
        return []
    argv = ["ki-dev", "step", bead, "--step", "review", "--next-turn"]
    for option, values in (
        (ARGS_OPTION, decision.preflight_args),
        (SKIP_OPTION, decision.preflight_skip),
    ):
        for name, text in values.items():
            argv += [option, f"{name}={text}"]
    return [
        "",
        "Prüfsteuerung des Reviewers (nicht angewendet; Teillauf ohne "
        "PASS), nach der Korrektur auszuführen:",
        shlex.join(argv),
    ]


def _recipient(judgement: Verdict) -> str:
    if judgement is Verdict.CHANGES:
        return "Umsetzer (bisherige Sitzung)"
    return "Mensch"


def _body(verdict: ReviewVerdict, judgement: Verdict) -> list[str]:
    if judgement is Verdict.CHANGES:
        return [
            f"Review-Befund ({verdict.event}, {judgement.value}, "
            f"{verdict.requirement_ref}): "
            f"{one_line(verdict.detail)}",
            "Bitte beheben. Melde anschließend nur zurück, was aus "
            "Diff und Prüfergebnissen nicht hervorgeht, etwa offene "
            "Entscheidungen oder Hindernisse.",
        ]
    detail = one_line(verdict.detail) or "ohne Begründung"
    return [
        f"Review-Urteil {judgement.value} ({verdict.event}): {detail}"
    ]

