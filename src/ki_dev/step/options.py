"""Optionsprüfung von ``ki-dev step``: Exit 2 vor jedem Lesen."""

from __future__ import annotations

from typing import NamedTuple

from ki_dev.ops.checks.options import (
    PreflightOptionError,
    parse_preflight_args,
    parse_preflight_skip,
)
from ki_dev.step.choices import (
    DEFAULT_REVIEW,
    FLOWS,
    ReviewTarget,
    Step,
)
from ki_dev.step.exits import fail


class Inputs(NamedTuple):
    """Eingaben der Folgerunde: --feedback-file, --decision-file."""

    feedback: str | None
    decision: str | None

class PreflightValues(NamedTuple):
    """Rohangaben von --preflight-args/--preflight-skip."""

    args: list[str]
    skip: list[str]

    def __bool__(self) -> bool:
        return bool(self.args or self.skip)

class PreflightRequest(NamedTuple):
    """Geprüfte Vorlauf-Optionen: Zusatzargumente und Auslassungen."""

    extra: dict[str, tuple[str, ...]]
    skip: dict[str, str]

NO_PREFLIGHT_OPTIONS = PreflightRequest({}, {})

def flow_name(step: Step, review_of: ReviewTarget | None) -> str:
    """Ablauf des Aufrufs (``flow/<NAME>.toml``): bei ``--step review``
    der Prüfgegenstand (ohne Angabe :data:`DEFAULT_REVIEW`), sonst der
    Schritt."""
    if step is Step.REVIEW:
        target = review_of or ReviewTarget(DEFAULT_REVIEW)
    else:
        target = step
    return FLOWS[target.value]

def review_target(flow: str) -> ReviewTarget:
    """Prüfgegenstand eines gespeicherten Ablaufs (Umkehrung)."""
    phases = {name: phase for phase, name in FLOWS.items()}
    return ReviewTarget(phases[flow])

def review_options(
    step: Step,
    review_of: ReviewTarget | None,
    preflight: bool,
    options: PreflightValues,
    next_turn: bool,
    feedback_file: str | None,
) -> PreflightRequest:
    """--review-of/--preflight-*/--next-turn/--feedback-file vor jedem
    Lesen prüfen.

    Gibt die zerlegten Vorlauf-Optionen zurück; sie gelten nur für den
    Vorlauf (``preflight``: der Ablauf bindet ihn).
    """
    if review_of is not None and step is not Step.REVIEW:
        fail(
            "--review-of ist nur zusammen mit --step review zulässig",
            code=2,
        )
    if next_turn and step is not Step.REVIEW:
        fail(
            "--next-turn ist nur zusammen mit --step review zulässig",
            code=2,
        )
    if feedback_file is not None and not next_turn:
        fail(
            "--feedback-file ist nur zusammen mit --next-turn zulässig",
            code=2,
        )
    if not options:
        return NO_PREFLIGHT_OPTIONS
    if step is not Step.REVIEW or not preflight:
        fail(
            "--preflight-args/--preflight-skip gelten nur für den "
            "Vorlauf: --step review (Prüfgegenstand implement)",
            code=2,
        )
    try:
        return PreflightRequest(
            parse_preflight_args(options.args),
            parse_preflight_skip(options.skip),
        )
    except PreflightOptionError as exc:
        fail(f"Aufruf ungültig: {exc}", code=2)

def check_decision_options(
    preflight: bool,
    options: PreflightValues,
    next_turn: bool,
    inputs: Inputs,
) -> None:
    """--decision-file vor jedem Lesen prüfen: nur Folgerunde der
    Umsetzungs-Review, ohne Vorlauf-Optionen und ohne Rückmeldung."""
    if inputs.decision is None:
        return
    if not next_turn:
        fail(
            "--decision-file ist nur zusammen mit --next-turn zulässig",
            code=2,
        )
    if not preflight or options:
        fail(
            "--decision-file gilt nur für die Umsetzungs-Review, ohne "
            "--preflight-args/--preflight-skip",
            code=2,
        )
    if inputs.feedback is not None:
        fail(
            "--decision-file und --feedback-file schließen sich aus",
            code=2,
        )
