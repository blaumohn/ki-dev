"""Zustandstabelle step-flow.toml: Gültigkeit, Erreichbarkeit, Läufe.

Die Tabelle ist endlich; deshalb wird die Erreichbarkeit des Endes
erschöpfend geprüft. Hypothesis simuliert Agentenausgaben (Befundlisten
und beliebige Ereignisfolgen) und prüft die Bedeutung der Klassen und
die Rückkehr jedes Laufs zum Ende.
"""

from __future__ import annotations

import copy
import re
import tomllib
from functools import partial
from importlib.resources import files
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from typer.testing import CliRunner

from ki_dev import handoff_cli
from ki_dev.cli import app
from ki_dev.handoff import (
    HandoffIssue,
    ReviewTarget,
    Step,
    flow_state,
)
from ki_dev.handoff import (
    render_handoff as _render_handoff,
)
from ki_dev.step_flow import (
    FILE_NAME,
    PASS,
    StepFlowError,
    load_step_flow,
    parse_step_flow,
    reaching_end,
)

FLOW = load_step_flow()
render_handoff = partial(_render_handoff, flow=FLOW)
CLASSES = list(FLOW.precedence)
# Ereignisse, mit denen ein Lauf vorankommt: Review besteht, Schreiber
# ist fertig, Mensch nimmt an, neue Quelle ist importiert.
PROGRESS = ("PASS", "erledigt", "annehmen", "importiert")


def _raw() -> dict:
    text = files("ki_dev").joinpath(FILE_NAME).read_text("utf-8")
    return tomllib.loads(text)


def test_shipped_table_is_valid_and_complete():
    assert FLOW.start == "map"
    assert FLOW.end == "fertig"
    phases = ("map", "graph", "materialize", "build")
    for phase in phases:
        for suffix in ("", ".review", ".korrektur", ".entscheidung"):
            assert f"{phase}{suffix}" in FLOW.states
    assert {"quelle", "fertig"} <= set(FLOW.states)


def test_every_state_reaches_the_end_exhaustively():
    assert reaching_end(FLOW) == set(FLOW.states)


def test_new_source_always_returns_through_the_existing_map():
    (transition,) = FLOW.outgoing("quelle")
    assert transition.target == "map"
    assert "keine zweite" in transition.command


@pytest.mark.parametrize("step", list(Step))
def test_every_handoff_ends_with_its_flow_hint(step):
    issue = HandoffIssue(
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
    assert FLOW.states[f"{target.value}.review"].kind == "review"


def test_hint_inserts_bead_and_lists_every_transition():
    lines = FLOW.hint_lines("graph.review", "b-7")
    assert lines[0].startswith("Hinweis für den Menschen: Zustand")
    assert len(lines) == 1 + len(FLOW.outgoing("graph.review"))
    assert "`ki-dev step b-7 --step materialize`" in "\n".join(lines)
    assert "{bead}" not in "\n".join(lines)


# --- ungültige Tabellen ---------------------------------------------


def _drop_transition(raw, source, event):
    raw["uebergang"] = [
        t
        for t in raw["uebergang"]
        if not (t["von"] == source and t["bei"] == event)
    ]


def _mutations():
    def unknown_target(raw):
        raw["uebergang"][0]["nach"] = "nirgends"

    def missing_review_event(raw):
        _drop_transition(raw, "graph.review", "quelle")

    def dead_end(raw):
        # build.korrektur kommt nur noch zu sich selbst zurück.
        _drop_transition(raw, "build.korrektur", "erledigt")
        raw["uebergang"].append(
            {
                "von": "build.korrektur",
                "bei": "erledigt",
                "nach": "build.korrektur",
                "befehl": "x",
            }
        )

    def extra_key(raw):
        raw["unbekannt"] = 1

    def bad_verdict(raw):
        raw["befundklasse"]["fix"]["urteil"] = "FAIL"

    def duplicate_state(raw):
        raw["zustand"].append(dict(raw["zustand"][0]))

    def precedence_mismatch(raw):
        raw["vorrang"] = ["fix", "quelle"]

    def duplicate_transition(raw):
        raw["uebergang"].append(dict(raw["uebergang"][0]))

    def unknown_event(raw):
        raw["uebergang"][0]["bei"] = "vielleicht"

    def end_with_exit(raw):
        raw["uebergang"].append(
            {
                "von": "fertig",
                "bei": "erledigt",
                "nach": "map",
                "befehl": "x",
            }
        )

    return [
        (unknown_target, "uebergang.0.nach: unbekannter Zustand"),
        (
            missing_review_event,
            "graph.review: fehlende Ereignisse quelle",
        ),
        (dead_end, "Sackgasse"),
        (extra_key, "$: additionalProperties"),
        (bad_verdict, "befundklasse.fix.urteil: enum"),
        (duplicate_state, "zustand.18.id: doppelt"),
        (precedence_mismatch, "vorrang: muss genau die Befundklassen"),
        (duplicate_transition, "doppelter Übergang map bei erledigt"),
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
    with pytest.raises(StepFlowError, match=_escaped(message)):
        parse_step_flow(raw)


def _escaped(text: str) -> str:
    return re.escape(text)


# --- simulierte Agentenausgaben -------------------------------------


@given(st.lists(st.sampled_from(CLASSES)))
def test_review_event_and_verdict_follow_precedence(findings):
    event = FLOW.review_event(findings)
    if not findings:
        assert event == PASS
        assert FLOW.verdict(event) == PASS
        return
    assert event == next(c for c in FLOW.precedence if c in findings)
    needs_human = any(
        FLOW.classes[c].verdict == "NEEDS_DECISION" for c in findings
    )
    assert (FLOW.verdict(event) == "NEEDS_DECISION") is needs_human


@given(st.lists(st.integers(min_value=0, max_value=50), max_size=60))
def test_random_walk_ends_once_agents_make_progress(choices):
    """Beliebige Ereignisse (auch quelle, fix, vorlauf_rot), danach nur
    noch Fortschritt: Jeder Lauf erreicht fertig, und jeder Weg über
    quelle führt zurück zur bestehenden Karte (map)."""
    state = FLOW.start
    for choice in choices:
        if state == FLOW.end:
            return
        options = FLOW.outgoing(state)
        transition = options[choice % len(options)]
        if transition.source == "quelle":
            assert transition.target == "map"
        state = transition.target
    for _ in range(len(FLOW.states)):
        if state == FLOW.end:
            return
        state = _progress(state)
    assert state == FLOW.end


def _progress(state: str) -> str:
    events = {t.event: t.target for t in FLOW.outgoing(state)}
    for event in PROGRESS:
        if event in events:
            return events[event]
    raise AssertionError(f"kein Fortschritt aus {state}")


def test_unknown_class_or_event_is_visible():
    with pytest.raises(StepFlowError, match="unbekannte Befundklasse"):
        FLOW.review_event(["vielleicht"])
    with pytest.raises(StepFlowError, match="kein Review-Ereignis"):
        FLOW.verdict("erledigt")
    with pytest.raises(StepFlowError, match="unbekannter Zustand"):
        FLOW.hint_lines("nirgends", "x")


def test_readme_state_diagram_matches_table():
    """Jede Kante des README-Diagramms ist ein Übergang der Tabelle."""
    readme = (Path(__file__).parent.parent / "README.md").read_text()
    block = readme.split("stateDiagram-v2", 1)[1].split("```", 1)[0]
    pattern = r'^\s*state "([^"]+)" as (\S+)$'
    aliases = {
        alias: name for name, alias in re.findall(pattern, block, re.M)
    }
    edges = re.findall(r"^\s*(\S+) --> (\S+): (\S+)$", block, re.M)
    assert edges
    table = {(t.source, t.event, t.target) for t in FLOW.transitions}
    for source, target, event in edges:
        source = aliases.get(source, source)
        target = aliases.get(target, target)
        assert (source, event, target) in table


def test_renderer_uses_the_flow_it_is_given():
    """Die Tabelle ist ausdrückliche Eingabe des Renderers: eine andere
    Tabelle ändert den Hinweis ohne globale Eingriffe."""
    raw = copy.deepcopy(_raw())
    for transition in raw["uebergang"]:
        if transition["von"] == "build":
            transition["befehl"] = "EIGENER-BEFEHL {bead}"
    other = parse_step_flow(raw)
    issue = HandoffIssue(
        id="x-1",
        title="T",
        description="D",
        design="De",
        acceptance_criteria="AC",
        source_refs=["a.md"],
    )
    text = _render_handoff(issue, Step.BUILD, flow=other)
    assert "EIGENER-BEFEHL x-1" in text
    assert "EIGENER-BEFEHL" not in render_handoff(issue, Step.BUILD)


def test_cli_reports_invalid_table_at_its_boundary(monkeypatch):
    def broken():
        raise StepFlowError("step-flow.toml: $: additionalProperties")

    monkeypatch.setattr(handoff_cli, "load_step_flow", broken)
    monkeypatch.setattr(
        handoff_cli,
        "read_issue",
        lambda *_: pytest.fail("Bead gelesen trotz ungültiger Tabelle"),
    )
    monkeypatch.setattr(
        handoff_cli, "load_base_max_chars", lambda _: 4000
    )
    result = CliRunner().invoke(app, ["step", "x-1", "--step", "build"])
    assert result.exit_code == 1
    assert "Zustandstabelle ungültig" in result.stderr
