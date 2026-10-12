"""Gemeinsamer Review-Vertrag: Kern, Ereignisse, AC-Zerlegung."""

from __future__ import annotations

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ki_dev.flow.model import load_flow
from ki_dev.review_decision import (
    ReviewContractError,
    ReviewVerdict,
    bind_requirement,
    criterion_refs,
    load_json_object,
    parse_verdict,
    review_schema,
    split_acceptance_criteria,
)

MAP = load_flow("map")
IMPLEMENT = load_flow("implement")


def _core(event="fix", detail="x", ref="AC1") -> dict:
    return {"event": event, "detail": detail, "requirement_ref": ref}


def test_allowed_events_come_from_the_flow():
    """Ein Vokabular: das event-enum ist PASS plus die Befundklassen
    des jeweiligen Ablaufs, keine Code-Konstante."""
    for flow in (MAP, IMPLEMENT):
        enum = review_schema(flow)["properties"]["event"]["enum"]
        assert enum == ["PASS", *flow.priority]


def test_map_rejects_escalate_but_implement_accepts_it():
    value = _core("escalate", "Grenze", None)
    verdict = parse_verdict(value, IMPLEMENT)
    assert verdict.event == "escalate"
    assert IMPLEMENT.verdict(verdict.event) == "ESCALATE"
    with pytest.raises(ReviewContractError, match="event: ungültiger"):
        parse_verdict(value, MAP)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"event": "PASS", "detail": ""}, "requirement_ref: fehlt"),
        ({**_core(), "extra": 1}, "extra: unbekanntes Feld"),
        (_core(event="MAYBE"), "event: ungültiger Wert"),
        (_core(detail=5), "detail: falscher Typ"),
        (_core(ref=""), "requirement_ref: muss null oder nichtleer"),
        (_core(ref=1), "requirement_ref: muss null oder nichtleer"),
        (
            _core(detail="  "),
            "detail: Nicht-PASS braucht eine Begruendung",
        ),
        (
            _core("PASS", "", "AC1"),
            "requirement_ref: ist außer bei CHANGES-Ereignissen null",
        ),
    ],
)
def test_invalid_core_names_field_without_raw_value(value, message):
    with pytest.raises(ReviewContractError, match=message) as excinfo:
        parse_verdict(value, MAP)
    assert "MAYBE" not in str(excinfo.value)


@pytest.mark.parametrize("raw", ["PASS", "[]", "{", '"x"'])
def test_only_a_single_json_object_is_accepted(raw):
    with pytest.raises(ReviewContractError, match="JSON-Objekt"):
        load_json_object(raw)


@given(
    event=st.sampled_from(MAP.review_events()),
    detail=st.text(max_size=40),
    ref=st.one_of(st.none(), st.sampled_from(["AC1", "AC2", "AC9"])),
)
def test_valid_answers_parse_and_bind_like_the_loop(event, detail, ref):
    """Simulierte Reviewer-Antworten: Gültige Kerne werden angenommen;
    fix ohne passende AC-Referenz wird decision (NEEDS_DECISION), nie
    ein automatischer Auftrag."""
    value = _core(event, detail, ref)
    try:
        verdict = parse_verdict(json.loads(json.dumps(value)), MAP)
    except ReviewContractError:
        needs_detail = event != "PASS"
        assert (needs_detail and not detail.strip()) or (
            event != "fix" and ref is not None
        )
        return
    bound = bind_requirement(verdict, ("AC1", "AC2"), MAP)
    if event == "fix" and ref not in ("AC1", "AC2"):
        assert bound.event == "decision"
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
    verdict = ReviewVerdict("fix", "x", "AC2")
    bound = bind_requirement(verdict, ("AC1", "AC2"), MAP)
    assert bound is verdict
