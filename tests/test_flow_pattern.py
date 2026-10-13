"""Topologie-Muster: Phasen expandieren zu ihren Zuständen und
Kanten; Tippfehler in Parametern sind sichtbar."""

from __future__ import annotations

import copy
import re

import pytest

from ki_dev.flow.model import (
    FlowError,
    load_flow,
    parse_flow,
    read_raw,
    with_pattern_catalog,
)


def test_phases_expand_to_their_states_and_edges():
    flow = load_flow("implement_review")
    for local in ("", ".review", ".correction", ".decision"):
        assert f"implement{local}" in flow.states
    assert "implement.preflight" in flow.states
    assert "map.preflight" not in load_flow("map").states
    (passed,) = flow.candidates("implement.review", "PASS")
    assert passed.cond == ("full_checks",)
    assert passed.target == "finished"
    # Die Tatsachen des Vorlaufs sind Eingabe der Kante, mit Herkunft.
    assert passed.inputs == (("facts", "implement.preflight"),)
    (correction,) = flow.state("implement.correction").operations
    assert correction.inputs == (("verdict", "implement.review"),)
    (map_pass,) = load_flow("map").candidates("map.review", "PASS")
    assert (map_pass.cond, map_pass.target) == ((), "finished")


def _mutated(change) -> dict:
    raw = copy.deepcopy(with_pattern_catalog(read_raw("map")))
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
            lambda r: r["phase"][0].update(use="gibt_es_nicht"),
            "phase.0 (map): unbekanntes Muster gibt_es_nicht",
        ),
        (
            lambda r: r["phase"][0].pop("next"),
            "phase.0 (map): @next ohne next",
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
    with pytest.raises(FlowError, match="map.toml: \\$"):
        parse_flow(raw)


def test_flow_loads_review_patterns_from_shared_catalog():
    raw = read_raw("map")
    assert "pattern" not in raw
    assert raw["pattern_catalog"] == ["review"]
    assert {"review_core", "write_review"} <= set(
        with_pattern_catalog(raw)["pattern"]
    )


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda r: r.update(pattern_catalog=["gibt_es_nicht"]),
            "pattern_catalog.gibt_es_nicht: unbekannt",
        ),
        (
            lambda r: r.update(
                pattern={"write_review": {"extends": "review_core"}}
            ),
            "überschreibt gemeinsames Muster",
        ),
    ],
)
def test_shared_catalog_errors_are_visible(change, message):
    raw = copy.deepcopy(read_raw("map"))
    change(raw)
    with pytest.raises(FlowError, match=re.escape(message)):
        parse_flow(raw)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda r: r["phase"][0].update(
                input={"review": {"report": "nirgends"}}
            ),
            "input.review.report: unbekannt nirgends",
        ),
        (
            lambda r: r["phase"][0].update(
                input={"review": {"report": "@next"}}
            ),
            "input",
        ),
    ],
)
def test_input_origin_must_be_a_local_or_global_state(change, message):
    raw = _mutated(change)
    with pytest.raises(FlowError, match=message):
        parse_flow(raw)
