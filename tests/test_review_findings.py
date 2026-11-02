"""Prüffragen, Beobachtungen, Notizen und Kriterienform des Ablaufs
``implement``: vom Ablauf bis zur Anzeige für den Menschen."""

from __future__ import annotations

import json
import re

import pytest
from jsonschema import Draft202012Validator

from ki_dev.adapter.contract import (
    AgentProtocolError,
    ReviewRequest,
    RunTask,
)
from ki_dev.adapter.executors.contract import ExecutorSpec
from ki_dev.adapter.mock import MockReviewer
from ki_dev.flow.model import FlowError, load_flow, parse_flow
from ki_dev.flow_ops.implement.cli import result_document
from ki_dev.flow_ops.implement.commands import _bead_task, _task_text
from ki_dev.flow_ops.implement.history import (
    WIDTH,
    _open_observations,
    _round_lines,
)
from ki_dev.flow_ops.implement.machine import IMPLEMENT
from ki_dev.flow_ops.implement.machine.contract import Phase
from ki_dev.flow_ops.implement.review_output import (
    REVIEW_VOCABULARY,
    parse_review_decision,
    review_output_schema,
)
from ki_dev.flow_ops.implement.runtime import RunResult
from ki_dev.flow_ops.implement.turns import review_prompt
from ki_dev.ops.context.bead_input import (
    BeadInput,
    BeadInputInvalidError,
)
from ki_dev.ops.context.beads_reader import (
    BeadsReadError,
    read_issue,
    read_issue_with_notes,
)
from ki_dev.review_context import ReviewProjection
from ki_dev.review_decision import (
    ReviewContractError,
    cli_schema,
    criteria_form_problems,
    parse_verdict,
    review_schema,
)
from tests.fake_bd_command import BdScript
from tests.turn_helpers import REVIEW_FINDINGS

MAP = load_flow("map")
MOCK_SPEC = ExecutorSpec("mock", "mock", frozenset())
QUESTIONS = ("invalid_input", "fake_only", "open_notes")


def _core(**over) -> dict:
    return {
        "event": "PASS",
        "detail": "",
        "requirement_ref": None,
        **REVIEW_FINDINGS,
        **over,
    }


# --- Ablauf ---------------------------------------------------------


def test_flow_declares_the_three_questions_and_the_marker():
    assert tuple(IMPLEMENT.review_questions) == QUESTIONS
    assert IMPLEMENT.criteria_markers == ("error",)


def test_question_without_text_is_a_flow_error():
    raw = {
        "name": "x",
        "start": "a",
        "final": ["a"],
        "vocabulary": {"kinds": ["final"], "events": ["go"]},
        "state": [{"id": "a", "kind": "final"}],
        "transition": [],
        "finding_class": {"fix": {"verdict": "CHANGES", "text": "t"}},
        "priority": ["fix"],
        "review_question": {"q": {}},
    }
    with pytest.raises(FlowError, match="review_question"):
        parse_flow(raw)


# --- Antwortvertrag -------------------------------------------------


def test_verdict_carries_answers_and_observations():
    verdict = parse_verdict(
        _core(observations=["NaN geht durch"]), IMPLEMENT
    )
    assert verdict.observations == ("NaN geht durch",)
    assert set(verdict.answers) == set(QUESTIONS)


@pytest.mark.parametrize(
    ("over", "message"),
    [
        ({"answers": {}}, "answers.invalid_input, answers.fake_only"),
        (
            {"answers": {**REVIEW_FINDINGS["answers"], "neu": "x"}},
            "answers.neu: unbekanntes Feld",
        ),
        (
            {"answers": dict.fromkeys(QUESTIONS, " ")},
            "answers.fake_only: muss nichtleerer Text sein",
        ),
        ({"observations": "NaN"}, "observations: falscher Typ"),
        ({"observations": [""]}, "observations.0: muss nichtleer"),
    ],
)
def test_incomplete_findings_are_contract_errors(over, message):
    with pytest.raises(ReviewContractError, match=message):
        parse_verdict(_core(**over), IMPLEMENT)


def test_missing_fields_name_both():
    value = {"event": "PASS", "detail": "", "requirement_ref": None}
    with pytest.raises(
        ReviewContractError, match="answers, observations: fehlt"
    ):
        parse_verdict(value, IMPLEMENT)


def test_flow_without_questions_does_not_know_the_fields():
    value = {
        "event": "PASS",
        "detail": "",
        "requirement_ref": None,
        "observations": ["x"],
    }
    with pytest.raises(
        ReviewContractError, match="observations: unbek"
    ):
        parse_verdict(value, MAP)


def test_observation_keeps_the_event():
    decision = parse_review_decision(
        json.dumps(
            {
                "run_id": "r",
                "round_id": 1,
                **_core(observations=["totals() wirft bei -1"]),
            }
        ),
        run_id="r",
        round_id=1,
    )
    assert decision.event == "PASS"
    assert decision.observations == ("totals() wirft bei -1",)


# --- Schema für die CLI ---------------------------------------------


def _objects(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for value in schema.values():
            yield from _objects(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from _objects(value)


def test_cli_schema_has_the_form_both_clis_accept():
    """Oberstes allOf/anyOf/oneOf/enum/not lehnen beide mit HTTP 400 ab;
    Codex verlangt jedes Feld in ``required``, keine freien Felder."""
    schema = review_output_schema()
    assert schema["type"] == "object"
    assert not {"allOf", "anyOf", "oneOf", "enum", "not"} & set(schema)
    for item in _objects(schema):
        assert item["additionalProperties"] is False
        assert set(item["required"]) == set(item["properties"])
    Draft202012Validator.check_schema(schema)


def test_cli_schema_leaves_the_field_rules_to_ki_dev():
    """Die CLI lässt das durch, ki-dev weist es weiter ab."""
    answer = {
        "run_id": "r",
        "round_id": 1,
        **_core(event="decision", detail="x", requirement_ref="AC1"),
    }
    assert Draft202012Validator(review_output_schema()).is_valid(answer)
    with pytest.raises(AgentProtocolError, match="requirement_ref"):
        parse_review_decision(
            json.dumps(answer), run_id="r", round_id=1
        )


def test_cli_schema_does_not_change_the_contract_schema():
    assert "allOf" not in cli_schema(IMPLEMENT)
    assert "allOf" in review_schema(IMPLEMENT)


# --- Übergabe an den Review -----------------------------------------


def _task(tmp_path, text="Auftrag") -> RunTask:
    return RunTask(
        "r",
        text,
        (),
        tmp_path,
        "write",
        acceptance_criteria=("K",),
    )


def test_prompt_names_each_question_and_the_answer_form(tmp_path):
    prompt = review_prompt(
        _task(tmp_path),
        1,
        "Bericht",
        ReviewProjection("TASK\nAuftrag\n", ()),
        REVIEW_VOCABULARY,
    )
    for name, text in IMPLEMENT.review_questions.items():
        assert f"- {name}: {text}" in prompt
    assert '"answers":{"invalid_input":"..."' in prompt
    assert '"observations":["..."]' in prompt


def test_mock_answers_every_question(tmp_path):
    reviewer = MockReviewer(MOCK_SPEC)
    raw = reviewer.review(
        ReviewRequest(
            _task(tmp_path), 1, "p", REVIEW_VOCABULARY, "a"
        )
    )
    decision = parse_review_decision(raw, run_id="r", round_id=1)
    assert set(decision.answers) == set(QUESTIONS)


# --- Anzeige --------------------------------------------------------


def _review(event, *observations):
    return {
        "decision": {
            "event": event,
            "detail": "",
            "requirement_ref": None,
            "observations": list(observations),
        },
        "decisions": [],
    }


def test_history_shows_observations_completely_under_the_review():
    long = "limit_reasons lässt NaN durch: " + "sehr lang " * 30
    reviews = [_review("PASS", long, "AgentSession ungetestet")]
    parts = {"review": reviews}
    lines, _, _ = _round_lines(1, parts, 0)
    shown = " ".join(" ".join(lines).split())
    assert " ".join(long.split()) in shown
    assert "…" not in shown
    assert "Beobachtung: AgentSession ungetestet" in shown
    assert all(len(line) <= WIDTH for line in lines)


def test_history_shows_each_answer_completely():
    """Die Probe auf bed689c nannte ``cost_usd -1`` nur in ``answers``:
    Ein Mangel darf dort nicht verloren gehen, auch nicht gekürzt."""
    finding = "negatives cost_usd wirft statt zu halten " * 8
    review = _review("PASS")
    review["decision"]["answers"] = {
        "invalid_input": finding,
        "fake_only": "nichts gefunden",
    }
    lines, _, _ = _round_lines(1, {"review": [review]}, 0)
    shown = " ".join(" ".join(lines).split())
    assert f"invalid_input: {' '.join(finding.split())}" in shown
    assert "fake_only: nichts gefunden" in shown
    assert "…" not in shown
    assert all(len(line) <= WIDTH for line in lines)


def test_history_of_a_review_before_the_field_shows_none():
    review = {
        "decision": {
            "event": "PASS",
            "detail": "",
            "requirement_ref": None,
        },
        "decisions": [],
    }
    lines, _, _ = _round_lines(1, {"review": [review]}, 0)
    assert len(lines) == 1


def test_history_says_what_is_left_after_integration():
    rounds = {
        1: {"review": [_review("fix", "alt")]},
        2: {"review": [_review("PASS", "a", "b")]},
    }
    (line,) = _open_observations(rounds)
    assert "2 Beobachtungen" in line
    assert "bd close" in line
    assert _open_observations({1: {"review": [_review("PASS")]}}) == []
    assert _open_observations({}) == []


def test_result_document_names_observations_only_when_present():
    base = RunResult("r", "passed", 1, Phase.PASSED)
    assert "observations" not in result_document(base)
    with_finding = RunResult(
        "r", "passed", 1, Phase.PASSED, observations=("NaN",)
    )
    assert result_document(with_finding)["observations"] == ["NaN"]


# --- Notizen --------------------------------------------------------


def _bead(**over) -> dict:
    return {
        "id": "x-1",
        "title": "T",
        "description": "D",
        "design": "E",
        "acceptance_criteria": "1. K\n2. [error] entfällt: Grund",
        **over,
    }


def _bd(monkeypatch, tmp_path, bead) -> None:
    BdScript(tmp_path, stdout=json.dumps([bead])).install(monkeypatch)


def test_notes_reach_the_task_as_marked_hints(monkeypatch, tmp_path):
    _bd(monkeypatch, tmp_path, _bead(notes="NaN abweisen"))
    task = _bead_task("x-1", tmp_path)["task"]
    head, notes = task.split("Notizen aus dem Bead")
    assert "E" in head
    assert "bindend sind nur die" in notes
    assert notes.endswith("NaN abweisen")


@pytest.mark.parametrize("bead", [{}, {"notes": ""}, {"notes": "  \n"}])
def test_no_notes_leave_the_task_unchanged(monkeypatch, tmp_path, bead):
    _bd(monkeypatch, tmp_path, _bead(**bead))
    assert "Notizen" not in _bead_task("x-1", tmp_path)["task"]


def test_invalid_notes_are_rejected_not_dropped(monkeypatch, tmp_path):
    _bd(monkeypatch, tmp_path, _bead(notes=7))
    with pytest.raises(BeadsReadError, match="notes"):
        read_issue_with_notes("x-1", tmp_path)


def test_step_input_stays_without_notes(monkeypatch, tmp_path):
    """Grenze von ``step`` (docs/step.de.md): keine Notizen, auch nicht
    als Feld, das eine Vorlage aus Versehen nutzen könnte."""
    _bd(monkeypatch, tmp_path, _bead(notes="GEHEIM"))
    assert "GEHEIM" not in repr(read_issue("x-1", tmp_path))
    assert not hasattr(BeadInput(), "notes")


def test_task_with_notes_and_epics_keeps_the_order():
    issue = BeadInput(
        id="x",
        title="T",
        description="D",
        design="E",
        epic_context=(("p", "Hinweis"),),
    )
    text = _task_text(issue, "N")
    assert text.index("E") < text.index("\nN")
    assert text.index("\nN") < text.index("p: Hinweis")


# --- Form der Kriterien ---------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "1. [error] entfällt: nur Doku",
        "1. Normalfall\n2. [error] cost_usd -1: stopped mit Lücke",
        "1. A\n2. [real] echte Klasse\n3. [error] B",
    ],
)
def test_well_formed_criteria_have_no_problems(text):
    assert criteria_form_problems(text, ("error",)) == ()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("Nur ein Satz [error]", "nicht nummeriert"),
        ("1. A\n2. B", r"kein Kriterium mit \[error\]"),
        ("1. A erwähnt [error] mitten im Satz", r"kein Kriterium mit"),
        ("1. [Error] A", r"kein Kriterium mit"),
    ],
)
def test_form_problems_are_named(text, message):
    (problem,) = criteria_form_problems(text, ("error",))
    assert re.search(message, problem)


def test_flow_without_markers_only_needs_numbers():
    assert criteria_form_problems("1. A", ()) == ()


@pytest.mark.parametrize(
    "criteria",
    ["Unnummeriert", "1. A", "1. A\n3. [error] Lücke in den Nummern"],
)
def test_task_from_badly_formed_bead_is_refused(
    monkeypatch, tmp_path, criteria
):
    _bd(monkeypatch, tmp_path, _bead(acceptance_criteria=criteria))
    with pytest.raises(
        BeadInputInvalidError, match="acceptance_criteria"
    ):
        _bead_task("x-1", tmp_path)
