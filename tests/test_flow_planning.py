"""Planungsablauf (planning.toml): Gültigkeit, Erreichbarkeit, Läufe.

Die Tabelle ist endlich; deshalb wird die Erreichbarkeit des Endes
erschöpfend geprüft. Hypothesis simuliert Agentenausgaben (Befundlisten
und beliebige Ereignisfolgen) und prüft die Bedeutung der Klassen und
die Rückkehr jedes Laufs zum Ende.
"""

from __future__ import annotations

import copy
import re
from functools import partial

import pytest
from hypothesis import given
from hypothesis import strategies as st
from typer.testing import CliRunner

from ki_dev.cli import app
from ki_dev.flow.model import (
    PASS,
    FlowError,
    parse_flow,
    reaching_final,
    read_raw,
)
from ki_dev.flow.pattern import expand
from ki_dev.flow.planning import (
    PlanningFlow,
    load_planning_flow,
)
from ki_dev.ops.context.bead_input import BeadInput
from ki_dev.ops.context.blocks import flow_state
from ki_dev.ops.context.contract import ReviewTarget, Step
from ki_dev.step import boundary, projection
from tests.turn_helpers import render_handoff as _render_handoff

FLOW = load_planning_flow()
A = FLOW.flow
END = A.final[0]
render_handoff = partial(_render_handoff, flow=FLOW)
CLASSES = list(A.priority)
# Ereignisse, mit denen ein Lauf vorankommt: Review besteht, Schreiber
# ist fertig, Mensch nimmt an, neue Quelle ist importiert.
PROGRESS = ("PASS", "done", "checks_passed", "accept", "imported")


def _raw() -> dict:
    """Expandierter Planungsablauf als Rohdaten: die Mutationen prüfen
    das flache Format, das der Lader nach den Mustern prüft."""
    return expand(read_raw("planning"), "planning.toml")


def test_shipped_table_is_valid_and_complete():
    assert A.start == "map"
    assert END == "finished"
    phases = ("map", "graph", "materialize", "implement")
    for phase in phases:
        for suffix in ("", ".review", ".correction", ".decision"):
            assert f"{phase}{suffix}" in A.states
    assert {"source", "finished"} <= set(A.states)


def test_every_state_reaches_the_end_exhaustively():
    assert reaching_final(A) == set(A.states)


def test_new_source_always_returns_through_the_existing_map():
    (transition,) = FLOW.outgoing("source")
    assert transition.target == "map"
    assert "keine zweite" in transition.hint


@pytest.mark.parametrize("step", list(Step))
def test_every_handoff_ends_with_its_flow_hint(step):
    issue = BeadInput(
        id="x-1",
        title="T",
        description="D",
        design="De",
        acceptance_criteria="AC",
        source_refs=["a.md"],
    )
    text = render_handoff(issue, step)
    state = flow_state(step, None)
    assert text.rstrip().endswith(
        "\n".join(FLOW.hint_lines(state, "x-1"))
    )
    assert ("Befundklassen:" in text) is (step is Step.REVIEW)


@pytest.mark.parametrize("target", list(ReviewTarget))
def test_review_targets_map_to_review_states(target):
    assert flow_state(Step.REVIEW, target) == f"{target.value}.review"
    assert A.states[f"{target.value}.review"].kind == "review"


def test_hint_inserts_bead_and_lists_every_transition():
    lines = FLOW.hint_lines("graph.review", "b-7")
    assert lines[0].startswith("Hinweis für den Menschen: Zustand")
    assert len(lines) == 1 + len(FLOW.outgoing("graph.review"))
    assert "`ki-dev step b-7 --step materialize`" in "\n".join(lines)
    assert "{bead}" not in "\n".join(lines)


# --- ungültige Tabellen ---------------------------------------------


def _edge(raw, source, event) -> tuple[int, dict]:
    return next(
        (index, t)
        for index, t in enumerate(raw["transition"])
        if (t["source"], t["event"]) == (source, event)
    )


def _drop_transition(raw, source, event):
    raw["transition"] = [
        t
        for t in raw["transition"]
        if not (t["source"] == source and t["event"] == event)
    ]


def _mutations():
    def unknown_target(raw):
        raw["transition"][0]["target"] = "nirgends"

    def missing_review_event(raw):
        _drop_transition(raw, "graph.review", "source")

    def dead_end(raw):
        # implement.correction kommt nur noch zu sich selbst zurück.
        _drop_transition(raw, "implement.correction", "done")
        raw["transition"].append(
            {
                "source": "implement.correction",
                "event": "done",
                "target": "implement.correction",
                "hint": "x",
            }
        )

    def extra_key(raw):
        raw["unbekannt"] = 1

    def bad_verdict(raw):
        raw["finding_class"]["fix"]["verdict"] = "FAIL"

    def duplicate_state(raw):
        raw["state"].append(dict(raw["state"][0]))

    def precedence_mismatch(raw):
        raw["priority"] = ["fix", "source"]

    def duplicate_transition(raw):
        raw["transition"].append(dict(_edge(raw, "map", "done")[1]))

    def unknown_event(raw):
        raw["transition"][0]["event"] = "vielleicht"

    def end_with_exit(raw):
        raw["transition"].append(
            {
                "source": "finished",
                "event": "done",
                "target": "map",
                "hint": "x",
            }
        )

    def unknown_guard(raw):
        raw["transition"][0]["cond"] = ["irgendwas"]

    def unguarded_before_guarded(raw):
        index, edge = _edge(raw, "map", "done")
        raw["vocabulary"]["guards"].append("irgendwas")
        raw["transition"].insert(
            index + 1, dict(edge, cond=["irgendwas"])
        )

    def history_outside_wait(raw):
        raw["transition"][0]["target"] = "@history"

    def unknown_kind(raw):
        raw["state"][0]["kind"] = "traeumen"

    return [
        (
            unknown_guard,
            "transition.0.cond: unbekannte Wächter irgendwas",
        ),
        (
            unguarded_before_guarded,
            "doppelter Übergang map bei done",
        ),
        (history_outside_wait, "@history nur aus kind wait"),
        (unknown_kind, "state map: unbekannte kind traeumen"),
        (unknown_target, "transition.0.target: unbekannter Zustand"),
        (
            missing_review_event,
            "graph.review: fehlende Ereignisse source",
        ),
        (dead_end, "Sackgasse"),
        (extra_key, "$: additionalProperties"),
        (bad_verdict, "finding_class.fix.verdict: enum"),
        (duplicate_state, ".id: doppelt (map)"),
        (precedence_mismatch, "priority: muss genau die Befundklassen"),
        (duplicate_transition, "doppelter Übergang map bei done"),
        (unknown_event, "unbekanntes Ereignis vielleicht"),
        (end_with_exit, "Ende ohne Übergänge"),
    ]


@pytest.mark.parametrize(
    ("mutate", "message"),
    _mutations(),
    ids=lambda value: getattr(value, "__name__", "msg"),
)
def test_invalid_table_is_rejected_with_location(mutate, message):
    raw = copy.deepcopy(_raw())
    mutate(raw)
    with pytest.raises(FlowError, match=_escaped(message)):
        parse_flow(raw)


def _escaped(text: str) -> str:
    return re.escape(text)


# --- simulierte Agentenausgaben -------------------------------------


@given(st.lists(st.sampled_from(CLASSES)))
def test_review_event_and_verdict_follow_precedence(findings):
    event = A.strongest(findings)
    if not findings:
        assert event == PASS
        assert A.verdict(event) == PASS
        return
    assert event == next(c for c in A.priority if c in findings)
    needs_human = any(
        A.finding_classes[c].verdict == "NEEDS_DECISION"
        for c in findings
    )
    assert (A.verdict(event) == "NEEDS_DECISION") is needs_human


@given(st.lists(st.integers(min_value=0, max_value=50), max_size=60))
def test_random_walk_ends_once_agents_make_progress(choices):
    """Beliebige Ereignisse (auch source, fix, preflight_failed), danach
    nur noch Fortschritt: Jeder Lauf erreicht finished, und jeder Weg
    über source führt zurück zur bestehenden Karte (map)."""
    state = A.start
    for choice in choices:
        if state == END:
            return
        options = FLOW.outgoing(state)
        transition = options[choice % len(options)]
        if transition.source == "source":
            assert transition.target == "map"
        state = transition.target
    for _ in range(len(A.states)):
        if state == END:
            return
        state = _progress(state)
    assert state == END


def _progress(state: str) -> str:
    """Fortschritt: je Ereignis die erste Kante (Dateireihenfolge), also
    die mit erfüllten Wächtern (vollständiger Vorlauf, Stand
    unverändert)."""
    events: dict[str, str] = {}
    for t in FLOW.outgoing(state):
        events.setdefault(t.event, t.target)
    for event in PROGRESS:
        if event in events:
            return events[event]
    raise AssertionError(f"kein Fortschritt aus {state}")


def test_unknown_class_or_event_is_visible():
    with pytest.raises(FlowError, match="unbekannte Befundklasse"):
        A.strongest(["vielleicht"])
    with pytest.raises(FlowError, match="kein Review-Ereignis"):
        A.verdict("done")
    with pytest.raises(FlowError, match="unbekannter Zustand"):
        FLOW.hint_lines("nirgends", "x")


def test_renderer_uses_the_flow_it_is_given():
    """Die Tabelle ist ausdrückliche Eingabe des Renderers: eine andere
    Tabelle ändert den Hinweis ohne globale Eingriffe."""
    raw = copy.deepcopy(_raw())
    for transition in raw["transition"]:
        if transition["source"] == "implement":
            transition["hint"] = "EIGENER-BEFEHL {bead}"
    other = PlanningFlow(parse_flow(raw))
    issue = BeadInput(
        id="x-1",
        title="T",
        description="D",
        design="De",
        acceptance_criteria="AC",
        source_refs=["a.md"],
    )
    text = _render_handoff(issue, Step.IMPLEMENT, flow=other)
    assert "EIGENER-BEFEHL x-1" in text
    assert "EIGENER-BEFEHL" not in render_handoff(issue, Step.IMPLEMENT)


def test_cli_reports_invalid_table_at_its_boundary(monkeypatch):
    def broken():
        raise FlowError("planning.toml: $: additionalProperties")

    monkeypatch.setattr(boundary, "load_planning_flow", broken)
    monkeypatch.setattr(
        projection,
        "read_issue",
        lambda *_: pytest.fail("Bead gelesen trotz ungültiger Tabelle"),
    )
    monkeypatch.setattr(
        projection, "load_base_max_chars", lambda _: 4000
    )
    result = CliRunner().invoke(
        app, ["step", "x-1", "--step", "implement"]
    )
    assert result.exit_code == 1
    assert "Planungsablauf ungültig" in result.stderr
