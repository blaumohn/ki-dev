"""Topologie-Muster: Phasen expandieren zu ihren Zuständen und
Kanten; Tippfehler in Parametern sind sichtbar."""

from __future__ import annotations

import copy
import re

import pytest

from ki_dev.flow.model import FlowError, load_flow, parse_flow, read_raw


def test_phases_expand_to_their_states_and_edges():
    flow = load_flow("planning")
    for phase in ("map", "graph", "materialize", "implement"):
        for local in ("", ".review", ".correction", ".decision"):
            assert f"{phase}{local}" in flow.states
    assert "implement.preflight" in flow.states
    assert "map.preflight" not in flow.states
    unchanged, changed = flow.candidates("implement.review", "PASS")
    assert (unchanged.cond, unchanged.target) == (
        ("full_checks", "unchanged"),
        "finished",
    )
    assert (changed.cond, changed.target) == (
        ("full_checks", "!unchanged"),
        "implement.preflight",
    )
    (map_pass,) = flow.candidates("map.review", "PASS")
    assert (map_pass.cond, map_pass.target) == ((), "graph")


def _mutated(change) -> dict:
    raw = copy.deepcopy(read_raw("planning"))
    change(raw)
    return raw


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda r: r["phase"][0]["actor"].update(revue="x"),
            "phase.0 (map): actor.revue: unbekannt",
        ),
        (
            lambda r: r["phase"][0]["hint"]["review"].update(done="x"),
            "phase.0 (map): hint.review.done: keine Kante",
        ),
        (
            lambda r: r["phase"][1].update(use="gibt_es_nicht"),
            "phase.1 (graph): unbekanntes Muster gibt_es_nicht",
        ),
        (
            lambda r: r["phase"][2].pop("next"),
            "phase.2 (materialize): @next ohne next",
        ),
        (
            lambda r: r["pattern"]["review_core"].update(
                extends="write_review"
            ),
            "extends-Zyklus",
        ),
        (
            lambda r: r["pattern"]["write_review"]["transition"][
                0
            ].update(target="nirgends"),
            "unbekanntes Ziel nirgends",
        ),
    ],
)
def test_parameter_typos_are_visible(change, message):
    with pytest.raises(FlowError, match=re.escape(message)):
        parse_flow(_mutated(change))


def test_phase_needs_patterns():
    raw = _mutated(lambda r: r.pop("pattern"))
    with pytest.raises(FlowError, match="planning.toml: \\$"):
        parse_flow(raw)
