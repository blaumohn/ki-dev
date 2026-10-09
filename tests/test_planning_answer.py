"""Antworthülle des Planungsablaufs neben der des Lieferablaufs
(ki-dev-ablauf-qu7.3): beide umhüllen denselben Urteilskern."""

from __future__ import annotations

import json

import pytest

from ki_dev.adapter.contract import RunTask
from ki_dev.flow.planning import load_planning_flow
from ki_dev.ops.checks.options import CONTROL_SCHEMA, check_control
from ki_dev.review_decision import ReviewContractError
from ki_dev.runner import review_output
from ki_dev.runner.review_output import (
    AgentProtocolError,
    bind_review_decision,
    parse_planning_answer,
    parse_review_decision,
)

FLOW = load_planning_flow().flow
REFS = ["AC1", "AC2"]


def _raw(**fields) -> str:
    value = {
        "event": "PASS",
        "detail": "",
        "requirement_ref": None,
        "attempt": "x-1:1",
    }
    return json.dumps(value | fields)


def _accept(_verdict, _extras) -> None:
    """Prüfung, die alles annimmt."""


def _parse(raw: str, check=_accept):
    return parse_planning_answer(raw, FLOW, REFS, CONTROL_SCHEMA, check)


def test_answer_carries_verdict_and_attempt():
    answer = _parse(_raw())
    assert (answer.verdict.event, answer.attempt) == ("PASS", "x-1:1")
    assert answer.extras == {}


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"attempt": 3}, "attempt: muss nichtleerer Text sein"),
        ({"attempt": "  "}, "attempt: muss nichtleerer Text sein"),
    ],
)
def test_attempt_must_be_text(fields, message):
    with pytest.raises(AgentProtocolError, match=message):
        _parse(_raw(**fields))


def test_missing_attempt_names_the_field():
    value = json.loads(_raw())
    del value["attempt"]
    with pytest.raises(AgentProtocolError, match="attempt: fehlt"):
        _parse(json.dumps(value))


def test_unknown_field_is_refused_like_in_the_core():
    with pytest.raises(AgentProtocolError, match="unbekanntes Feld"):
        _parse(_raw(x=1))


def test_changes_is_bound_to_a_criterion_or_becomes_a_decision():
    bound = _parse(
        _raw(event="fix", detail="d", requirement_ref="AC2")
    )
    assert (bound.verdict.event, bound.verdict.requirement_ref) == (
        "fix",
        "AC2",
    )
    unbound = _parse(
        _raw(event="fix", detail="d", requirement_ref="AC9")
    )
    assert unbound.verdict.event == "decision"


def test_extras_reach_the_plugged_check():
    seen = []

    def check(verdict, extras):
        seen.append((verdict.event, dict(extras)))

    answer = _parse(
        _raw(event="decision", detail="d", preflight_skip={"a": "b"}),
        check,
    )
    assert seen == [("decision", {"preflight_skip": {"a": "b"}})]
    assert answer.extras == {"preflight_skip": {"a": "b"}}


def test_check_failures_become_protocol_errors():
    def check(_verdict, _extras):
        raise ReviewContractError("Prüfung gescheitert")

    with pytest.raises(AgentProtocolError, match="Prüfung gescheitert"):
        _parse(_raw(), check)


def test_control_with_pass_is_refused_without_reading_the_config():
    def never():
        raise AssertionError("Konfiguration darf nicht geladen werden")

    answer = _parse(_raw())
    with pytest.raises(ReviewContractError, match="bei PASS"):
        check_control(
            answer.verdict, {"preflight_args": {"tests": "-x"}}, never
        )
    check_control(answer.verdict, {}, never)


def test_both_wrappers_check_through_the_same_core_functions(
    monkeypatch, tmp_path
):
    """Lieferablauf und Planungsablauf prüfen und binden Antworten über
    dieselben Funktionen des gemeinsamen Kerns."""
    seen = []
    for name in ("parse_verdict", "bind_requirement"):
        original = getattr(review_output, name)

        def spy(*args, _name=name, _original=original, **kwargs):
            seen.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(review_output, name, spy)

    raw = json.dumps(
        {
            "run_id": "r",
            "round_id": 1,
            "event": "fix",
            "detail": "d",
            "requirement_ref": "AC1",
        }
    )
    task = RunTask(
        "r",
        "Auftrag",
        (),
        tmp_path,
        "write",
        acceptance_criteria=("K",),
    )
    decision = parse_review_decision(raw, run_id="r", round_id=1)
    bind_review_decision(decision, task)
    delivery = list(seen)
    seen.clear()
    _parse(_raw(event="fix", detail="d", requirement_ref="AC1"))
    assert delivery == seen == ["parse_verdict", "bind_requirement"]
