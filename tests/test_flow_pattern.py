"""Topologie-Muster: Expansion gleicht dem flach ausgeschriebenen
Ablauf; Tippfehler in Parametern sind sichtbar."""

from __future__ import annotations

import copy
import re
import tomllib
from pathlib import Path

import pytest

from ki_dev.flow.model import FlowError, load_flow, parse_flow, read_raw

FLAT = Path(__file__).parent / "fixtures" / "planning_flat.toml"


def _flat():
    return parse_flow(tomllib.loads(FLAT.read_text(encoding="utf-8")))


def test_expanded_planning_equals_the_flat_flow():
    expanded, flat = load_flow("planning"), _flat()
    assert expanded.states == flat.states
    assert set(expanded.transitions) == set(flat.transitions)
    for state in flat.states:
        assert expanded.outgoing(state) == flat.outgoing(state)
    assert expanded.finding_classes == flat.finding_classes


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
            lambda r: r["pattern"]["write_review"].update(
                extends="write_review_preflight"
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
