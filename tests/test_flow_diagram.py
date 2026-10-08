"""Mermaid-Diagramme der Abläufe: aus der Quelle erzeugt, eingebettet
und gegen die Ausgabe geprüft."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from ki_dev.cli import app
from ki_dev.flow.diagram import (
    diagram_markers,
    render_mermaid,
    sync_diagrams,
)
from ki_dev.flow.model import load_flow

ROOT = Path(__file__).parent.parent
DELIVERY = load_flow("delivery")
PLANNING = load_flow("planning")


def test_every_transition_is_an_edge_with_its_label():
    text = render_mermaid(PLANNING)
    for t in PLANNING.transitions:
        source = t.source.replace(".", "_")
        target = t.target.replace(".", "_")
        assert f"    {source} --> {target}: {t.event}" in text


def test_without_escalations_hides_exactly_the_escalation_edges():
    full = render_mermaid(DELIVERY).splitlines()
    main = render_mermaid(
        DELIVERY, without_escalations=True
    ).splitlines()
    hidden = sum(1 for t in DELIVERY.transitions if t.escalation)
    assert hidden > 0
    edges = [
        line for line in full if " --> " in line and "[*]" not in line
    ]
    shown = [
        line for line in main if " --> " in line and "[*]" not in line
    ]
    assert len(edges) - len(shown) == hidden


def test_history_is_a_pseudo_state_not_a_guess():
    text = render_mermaid(DELIVERY)
    assert 'state "@history" as paused_interactive_history' in text
    assert "paused_interactive --> paused_interactive_history" in text


def test_output_is_deterministic():
    assert render_mermaid(PLANNING) == render_mermaid(
        load_flow("planning")
    )


def test_readme_diagrams_equal_generated_output():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert diagram_markers(text) == ["delivery", "planning"]
    assert sync_diagrams(text, load_flow) == text


def test_cli_prints_the_diagram():
    result = CliRunner().invoke(
        app, ["flow", "show", "delivery", "--without-escalations"]
    )
    assert result.exit_code == 0
    assert result.output == render_mermaid(
        DELIVERY, without_escalations=True
    )


def test_cli_rejects_unknown_flow_with_exit_2():
    result = CliRunner().invoke(app, ["flow", "show", "nirgends"])
    assert result.exit_code == 2
