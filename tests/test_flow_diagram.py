"""Mermaid-Diagramme der Abläufe: aus der Quelle erzeugt, eingebettet
und gegen die Ausgabe geprüft."""

from __future__ import annotations

import copy
from pathlib import Path

from typer.testing import CliRunner

from ki_dev.cli import app
from ki_dev.flow.diagram import (
    diagram_markers,
    render_mermaid,
    sync_diagrams,
)
from ki_dev.flow.model import load_flow, parse_flow, read_raw

ROOT = Path(__file__).parent.parent
IMPLEMENT = load_flow("implement")
PLANNING = load_flow("planning")


def test_every_transition_is_an_edge_with_its_label():
    text = render_mermaid(PLANNING)
    for t in PLANNING.transitions:
        source = t.source.replace(".", "_")
        target = t.target.replace(".", "_")
        assert f"    {source} --> {target}: {t.event}" in text


def test_without_escalations_hides_exactly_the_escalation_edges():
    full = render_mermaid(IMPLEMENT).splitlines()
    main = render_mermaid(
        IMPLEMENT, without_escalations=True
    ).splitlines()
    hidden = sum(1 for t in IMPLEMENT.transitions if t.escalation)
    assert hidden > 0
    edges = [
        line for line in full if " --> " in line and "[*]" not in line
    ]
    shown = [
        line for line in main if " --> " in line and "[*]" not in line
    ]
    assert len(edges) - len(shown) == hidden


def test_history_is_a_pseudo_state_not_a_guess():
    """Kein Paketablauf nutzt History; das Format kennt sie (SCXML)."""
    raw = copy.deepcopy(read_raw("implement"))
    raw["statechart"]["states"]["active"]["history"] = {
        "h": {"type": "shallow"}
    }
    raw["statechart"]["states"]["waiting_decision"]["transitions"] = [
        {"event": "resume_requested", "target": "h"}
    ]
    text = render_mermaid(parse_flow(raw))
    assert 'state "@history" as waiting_decision_history' in text
    assert "waiting_decision --> waiting_decision_history" in text


def test_output_is_deterministic():
    assert render_mermaid(PLANNING) == render_mermaid(
        load_flow("planning")
    )


def test_readme_diagrams_equal_generated_output():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert diagram_markers(text) == ["implement", "planning"]
    assert sync_diagrams(text, load_flow) == text


def test_cli_prints_the_diagram():
    result = CliRunner().invoke(
        app, ["flow", "show", "implement", "--without-escalations"]
    )
    assert result.exit_code == 0
    assert result.output == render_mermaid(
        IMPLEMENT, without_escalations=True
    )


def test_cli_rejects_unknown_flow_with_exit_2():
    result = CliRunner().invoke(app, ["flow", "show", "nirgends"])
    assert result.exit_code == 2
