"""Laufzustand je Bead: step setzt fort, Wächter sehen den Zustand,
Sprünge stehen im Protokoll."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from ki_dev.cli import app
from ki_dev.flow.model import load_flow
from ki_dev.run_store import RunStore
from ki_dev.runner.events import check_conformance
from ki_dev.step.state import load_state
from tests.fake_bd_command import BdScript
from tests.guideline_fixtures import write_guidelines
from tests.test_step_cli import FULL, _command, _preflight_project

runner = CliRunner()
PLANNING = load_flow("planning")
FAIL = "import sys; sys.exit(1)"


@pytest.fixture
def bd(monkeypatch, tmp_path_factory):
    fake = BdScript(
        tmp_path_factory.mktemp("bd"),
        stdout=json.dumps([FULL]),
        stderr="",
    )
    fake.install(monkeypatch)
    return fake


@pytest.fixture
def project(tmp_path, monkeypatch):
    def make(code="print(1)"):
        _preflight_project(
            tmp_path, checks=f"[{_command('tests', code)}]"
        )
        write_guidelines(tmp_path)
        monkeypatch.chdir(tmp_path)
        return tmp_path

    return make


def _events(root):
    return RunStore(root, "x-1").load_events()


def test_continue_after_writing_runs_preflight_and_hands_to_review(
    bd, project, step_state_root
):
    project()
    first = runner.invoke(app, ["step", "x-1", "--step", "implement"])
    assert first.exit_code == 0
    assert load_state("x-1").state == "implement"

    result = runner.invoke(app, ["step", "x-1"])
    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("Schritt: review\n")
    assert load_state("x-1").state == "implement.review"
    events = _events(step_state_root)
    assert [(e["state"], e["event"], e["adapter"]) for e in events] == [
        ("implement", "done", "manual"),
        ("implement.preflight", "checks_passed", "ki-dev"),
    ]
    assert check_conformance(PLANNING, events) == []


def test_continue_after_red_preflight_is_the_next_turn(
    bd, project, tmp_path
):
    project(FAIL)
    red = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert red.exit_code == 1
    assert load_state("x-1").state == "implement.correction"

    (tmp_path / "pyproject.toml").write_text(
        "[tool.ki-dev.handoff.preflight]\ncorrections = []\n"
        f"checks = [{_command('tests', 'print(1)')}]\n"
    )
    result = runner.invoke(app, ["step", "x-1"])
    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("Empfänger: Review-Agent")


def test_pass_after_partial_run_is_refused_from_saved_state(
    bd, project, tmp_path
):
    project()
    partial = runner.invoke(
        app,
        [
            "step",
            "x-1",
            "--step",
            "review",
            "--preflight-skip",
            "tests=Doku",
        ],
    )
    assert partial.exit_code == 0
    assert load_state("x-1").facts == frozenset()
    answer = tmp_path / "antwort.json"
    answer.write_text(
        '{"event": "PASS", "detail": "", "requirement_ref": null}'
    )
    result = runner.invoke(
        app,
        [
            "step",
            "x-1",
            "--step",
            "review",
            "--next-turn",
            "--decision-file",
            str(answer),
        ],
    )
    assert result.exit_code == 2
    assert "Teillauf: kein PASS" in result.stderr


def test_continue_without_saved_state_names_the_start(bd, project):
    project()
    result = runner.invoke(app, ["step", "x-1"])
    assert result.exit_code == 2
    assert "kein gespeicherter Zustand" in result.stderr
    assert bd.calls == []


def test_continue_at_review_lists_the_next_steps(bd, project):
    project()
    runner.invoke(app, ["step", "x-1", "--step", "review"])
    result = runner.invoke(app, ["step", "x-1"])
    assert result.exit_code == 0
    assert result.stdout.startswith(
        "Hinweis für den Menschen: Zustand implement.review"
    )
    assert "- fix → implement.correction:" in result.stdout


def test_jump_is_noted_and_visible_in_the_log(
    bd, project, step_state_root
):
    project()
    runner.invoke(
        app, ["step", "x-1", "--step", "review", "--review-of", "map"]
    )
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 0
    assert "letzter Halt map.review" in result.stderr
    problems = check_conformance(PLANNING, _events(step_state_root))
    assert problems == [
        "1: keine Kante map.review --@jump--> implement"
    ]


def test_jump_without_any_edge_is_still_logged(
    bd, project, step_state_root
):
    """--step implement, dann --step map: keiner der Aufrufe nimmt eine
    Kante, der Sprung steht trotzdem im Protokoll."""
    project()
    runner.invoke(app, ["step", "x-1", "--step", "implement"])
    runner.invoke(app, ["step", "x-1", "--step", "map"])
    events = _events(step_state_root)
    assert [(e["state"], e["event"], e["target"]) for e in events] == [
        ("implement", "@jump", "map")
    ]
    assert check_conformance(PLANNING, events) == [
        "0: keine Kante implement --@jump--> map"
    ]


def test_pass_while_waiting_in_correction_is_refused(
    bd, project, tmp_path
):
    """Roter vollständiger Vorlauf: der Lauf wartet in
    implement.correction; eine PASS-Antwort darf ihn nicht beenden."""
    project(FAIL)
    red = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert red.exit_code == 1
    answer = tmp_path / "antwort.json"
    answer.write_text(
        '{"event": "PASS", "detail": "", "requirement_ref": null}'
    )
    result = runner.invoke(
        app,
        [
            "step",
            "x-1",
            "--step",
            "review",
            "--next-turn",
            "--decision-file",
            str(answer),
        ],
    )
    assert result.exit_code == 2
    assert "wartet in implement.correction" in result.stderr
    assert load_state("x-1").state == "implement.correction"


def test_continue_rejects_further_options(bd, project):
    project()
    result = runner.invoke(app, ["step", "x-1", "--next-turn"])
    assert result.exit_code == 2
