"""--decision-file: Reviewer-Antwort lesen, nächste Nachricht wählen.

Datenfluss: Die Build-Review endet mit genau einem JSON-Objekt im
gemeinsamen Vertrag (review_decision). Der Mensch gibt es mit
``ki-dev step BEAD_ID --step review --next-turn --decision-file
DATEI|-`` weiter. step prüft es, bindet CHANGES an ein Abnahmekriterium
des Beads (sonst NEEDS_DECISION wie im Loop) und gibt die Nachricht für
den Empfänger aus, den step-flow.toml für ``build.review`` und dieses
Urteil nennt. Kein Vorlauf, keine Schreibwirkung, kein Agentenstart.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import BinaryIO

from ki_dev.handoff import HandoffIssue, criteria_with_refs, one_line
from ki_dev.handoff_next_turn import read_bounded_text
from ki_dev.review_decision import (
    STEP_ACTIONS,
    ReviewAction,
    ReviewContractError,
    ReviewVerdict,
    bind_requirement,
    load_json_object,
    parse_verdict,
)
from ki_dev.step_flow import load_step_flow

# Obergrenze der eingelesenen Antwort (Zeichen); nie gekürzt.
DECISION_MAX_CHARS = 20000
_REVIEW_STATE = "build.review"
_WHAT = "Review-Antwort"


class DecisionInputError(ValueError):
    """Antwort ungültig oder zu lang (Exit 2), ohne Rohwerte."""


def read_decision(source: str, stdin: Callable[[], BinaryIO]) -> str:
    text = read_bounded_text(source, DECISION_MAX_CHARS, stdin, _WHAT)
    if len(text) > DECISION_MAX_CHARS:
        raise DecisionInputError(
            f"{_WHAT} überschreitet {DECISION_MAX_CHARS} Zeichen; "
            "keine Kürzung"
        )
    return text


def parse_step_decision(raw: str, issue: HandoffIssue) -> ReviewVerdict:
    """Vertrag prüfen und an die Abnahmekriterien des Beads binden."""
    try:
        verdict = parse_verdict(load_json_object(raw), STEP_ACTIONS)
    except ReviewContractError as exc:
        raise DecisionInputError(f"{_WHAT} ungültig: {exc}") from exc
    refs = [ref for ref, _ in criteria_with_refs(issue)]
    return bind_requirement(verdict, refs)


def render_decision_turn(
    issue: HandoffIssue, verdict: ReviewVerdict
) -> str:
    """Nachricht an den Empfänger laut Zustandstabelle."""
    flow = load_step_flow()
    events = flow.events_for_verdict(verdict.action.value)
    bead = issue.id
    lines = [
        f"Empfänger: {_recipient(verdict.action)}",
        f"Bead: {one_line(bead)} - {one_line(issue.title)}",
        "",
        *_body(verdict),
        "",
        *flow.hint_lines(_REVIEW_STATE, one_line(bead), events),
    ]
    return "\n".join(lines) + "\n"


def _recipient(action: ReviewAction) -> str:
    if action is ReviewAction.CHANGES:
        return "Bau-Agent (bisherige Sitzung)"
    return "Mensch"


def _body(verdict: ReviewVerdict) -> list[str]:
    if verdict.action is ReviewAction.CHANGES:
        return [
            f"Review-Befund (CHANGES, {verdict.requirement_ref}): "
            f"{one_line(verdict.detail)}",
            "Bitte beheben. Melde anschließend nur zurück, was aus "
            "Diff und Prüfergebnissen nicht hervorgeht, etwa offene "
            "Entscheidungen oder Hindernisse.",
        ]
    detail = one_line(verdict.detail) or "ohne Begründung"
    return [f"Review-Urteil {verdict.action.value}: {detail}"]

