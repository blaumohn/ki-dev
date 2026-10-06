"""Gemeinsamer Build-Review-Vertrag: Kern, Aktionen, AC-Zerlegung."""

from __future__ import annotations

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ki_dev.review_decision import (
    LOOP_ACTIONS,
    STEP_ACTIONS,
    ReviewAction,
    ReviewContractError,
    ReviewVerdict,
    bind_requirement,
    criterion_refs,
    load_json_object,
    parse_verdict,
    split_acceptance_criteria,
)


def _core(action="CHANGES", detail="x", ref="AC1") -> dict:
    return {"action": action, "detail": detail, "requirement_ref": ref}


def test_step_rejects_escalate_but_loop_accepts_it():
    value = _core("ESCALATE", "Grenze", None)
    assert (
        parse_verdict(value, LOOP_ACTIONS).action
        is ReviewAction.ESCALATE
    )
    with pytest.raises(ReviewContractError, match="action: ungültiger"):
        parse_verdict(value, STEP_ACTIONS)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"action": "PASS", "detail": ""}, "requirement_ref: fehlt"),
        ({**_core(), "extra": 1}, "extra: unbekanntes Feld"),
        (_core(action="MAYBE"), "action: ungültiger Wert"),
        (_core(detail=5), "detail: falscher Typ"),
        (_core(ref=""), "requirement_ref: muss null oder nichtleer"),
        (_core(ref=1), "requirement_ref: muss null oder nichtleer"),
        (
            _core(detail="  "),
            "detail: CHANGES braucht eine Begruendung",
        ),
        (_core("PASS", "", "AC1"), "PASS darf kein requirement_ref"),
    ],
)
def test_invalid_core_names_field_without_raw_value(value, message):
    with pytest.raises(ReviewContractError, match=message) as excinfo:
        parse_verdict(value, STEP_ACTIONS)
    assert "MAYBE" not in str(excinfo.value)


@pytest.mark.parametrize("raw", ["PASS", "[]", "{", '"x"'])
def test_only_a_single_json_object_is_accepted(raw):
    with pytest.raises(ReviewContractError, match="JSON-Objekt"):
        load_json_object(raw)


@given(
    action=st.sampled_from(STEP_ACTIONS),
    detail=st.text(max_size=40),
    ref=st.one_of(st.none(), st.sampled_from(["AC1", "AC2", "AC9"])),
)
def test_valid_answers_parse_and_bind_like_the_loop(
    action, detail, ref
):
    """Simulierte Reviewer-Antworten: Gültige Kerne werden angenommen;
    CHANGES ohne passende AC-Referenz wird NEEDS_DECISION, nie ein
    automatischer Bauauftrag."""
    value = _core(action.value, detail, ref)
    try:
        verdict = parse_verdict(
            json.loads(json.dumps(value)), STEP_ACTIONS
        )
    except ReviewContractError:
        needs_detail = action is not ReviewAction.PASS
        assert (needs_detail and not detail.strip()) or (
            action is not ReviewAction.CHANGES and ref is not None
        )
        return
    bound = bind_requirement(verdict, ("AC1", "AC2"))
    if action is ReviewAction.CHANGES and ref not in ("AC1", "AC2"):
        assert bound.action is ReviewAction.NEEDS_DECISION
        assert bound.requirement_ref is None
    else:
        assert bound == verdict


def test_split_numbered_criteria():
    text = "1. Erstens\nmehrzeilig\n2. Zweitens\n3. Drittens"
    criteria = split_acceptance_criteria(text)
    assert criteria == ("Erstens\nmehrzeilig", "Zweitens", "Drittens")
    assert criterion_refs(criteria) == ("AC1", "AC2", "AC3")


def test_unnumbered_field_is_one_criterion():
    assert split_acceptance_criteria(" Ein Kriterium. ") == (
        "Ein Kriterium.",
    )


@pytest.mark.parametrize(
    "text", ["1. a\n3. b", "2. a\n3. b", "1. a\n1. b"]
)
def test_gaps_or_duplicates_are_visible_errors(text):
    with pytest.raises(ReviewContractError, match="fortlaufend"):
        split_acceptance_criteria(text)


def test_bind_keeps_bound_changes():
    verdict = ReviewVerdict(ReviewAction.CHANGES, "x", "AC2")
    assert bind_requirement(verdict, ("AC1", "AC2")) is verdict
