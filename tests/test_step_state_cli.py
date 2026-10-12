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
from tests.turn_helpers import attempt_of

runner = CliRunner()
IMPLEMENT_REVIEW = load_flow("implement_review")
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


# Kennung des ersten wartenden Reviews eines frischen Beads.
PASS_ANSWER = json.dumps(
    {
        "event": "PASS",
        "detail": "",
        "requirement_ref": None,
        "attempt": "x-1:1",
    }
)


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
    assert check_conformance(IMPLEMENT_REVIEW, events) == []


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
        PASS_ANSWER
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
    """Innerhalb eines Ablaufs: Review von map, dann neu bei map."""
    project()
    runner.invoke(
        app, ["step", "x-1", "--step", "review", "--review-of", "map"]
    )
    result = runner.invoke(app, ["step", "x-1", "--step", "map"])
    assert result.exit_code == 0
    assert "letzter Halt map.review" in result.stderr
    problems = check_conformance(
        load_flow("map"), _events(step_state_root)
    )
    assert problems == ["1: keine Kante map.review --@jump--> map"]


def test_other_flow_is_a_new_run_not_a_jump(
    bd, project, step_state_root
):
    """--step implement, dann --step map: ein anderer Ablauf beginnt
    einen neuen Lauf; kein Sprung im Protokoll."""
    project()
    runner.invoke(app, ["step", "x-1", "--step", "implement"])
    result = runner.invoke(app, ["step", "x-1", "--step", "map"])
    assert result.exit_code == 0
    assert "letzter Halt" not in result.stderr
    assert _events(step_state_root) == []
    assert load_state("x-1").flow == "map"


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
        PASS_ANSWER
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


def _pass_answer(tmp_path):
    answer = tmp_path / "antwort.json"
    answer.write_text(
        PASS_ANSWER
    )
    return [
        "step",
        "x-1",
        "--step",
        "review",
        "--next-turn",
        "--decision-file",
        str(answer),
    ]


def test_pass_without_any_preflight_is_refused(bd, project, tmp_path):
    """Ohne gespeicherten Halt lief kein Vorlauf: auch bei roten
    Prüfungen darf eine PASS-Antwort den Lauf nicht beenden."""
    project(FAIL)
    result = runner.invoke(app, _pass_answer(tmp_path))
    assert result.exit_code == 2
    assert "kein Vorlauf in diesem Lauf" in result.stderr
    assert "ki-dev step x-1 --step review" in result.stderr
    assert load_state("x-1") is None


def test_pass_after_full_preflight_finishes(bd, project, tmp_path):
    project()
    review = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert review.exit_code == 0, review.stderr
    result = runner.invoke(app, _pass_answer(tmp_path))
    assert result.exit_code == 0, result.stderr
    assert load_state("x-1").state == "finished"


def _reviewed_then(change, bd, project, step_state_root, tmp_path):
    root = project()
    review = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert review.exit_code == 0, review.stderr
    change(root, bd)
    result = runner.invoke(app, _pass_answer(tmp_path))
    return result, _events(step_state_root)


def _new_file(root, _bd):
    (root / "neu.py").write_text("x = 1\n")


def _no_change(_root, _bd):
    pass


def _new_criterion(_root, bd):
    bd.state["stdout"] = json.dumps(
        [{**FULL, "acceptance_criteria": "AC und neu"}]
    )


@pytest.mark.parametrize(
    "change", [_new_file, _new_criterion], ids=["datei", "bead"]
)
def test_pass_after_change_runs_preflight_again(
    change, bd, project, step_state_root, tmp_path
):
    """Synchron wie freeze bei run: Arbeitsbaum oder Bead seit dem
    Vorlauf geändert, also kein PASS, sondern neuer Vorlauf und eine
    Folgerunde an das Review."""
    result, events = _reviewed_then(
        change, bd, project, step_state_root, tmp_path
    )
    assert result.exit_code == 0, result.stderr
    assert "Stand seit dem Vorlauf geändert" in result.stderr
    assert "bisherige, vom Schreibagenten getrennte Sitzung" in (
        result.stdout
    )
    assert load_state("x-1").state == "implement.review"
    assert [(e["state"], e["event"]) for e in events][-2:] == [
        ("implement.review", "PASS"),
        ("implement.preflight", "checks_passed"),
    ]
    assert check_conformance(IMPLEMENT_REVIEW, events) == []


def test_answer_file_in_project_is_not_a_change(
    bd, project, step_state_root, tmp_path
):
    """Die Antwortdatei ist Eingabe an ki-dev, keine Arbeit."""
    result, _ = _reviewed_then(
        _no_change, bd, project, step_state_root, tmp_path
    )
    assert result.exit_code == 0, result.stderr
    assert load_state("x-1").state == "finished"


def test_pass_without_git_worktree_is_refused(
    bd, tmp_path, monkeypatch
):
    """Der Vorlauf braucht kein Git, ein PASS schon: ohne Stand nichts
    zu vergleichen."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ki-dev.handoff.preflight]\ncorrections = []\n"
        f"checks = [{_command('tests', 'print(1)')}]\n"
    )
    write_guidelines(tmp_path)
    monkeypatch.chdir(tmp_path)
    review = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert review.exit_code == 0, review.stderr
    result = runner.invoke(app, _pass_answer(tmp_path))
    assert result.exit_code == 2
    assert "Git-Arbeitsverzeichnis" in result.stderr
    assert load_state("x-1").state == "implement.review"


def test_halt_from_other_flow_needs_explicit_step(
    bd, project, monkeypatch
):
    project()
    first = runner.invoke(app, ["step", "x-1", "--step", "map"])
    assert first.exit_code == 0, first.stderr
    monkeypatch.setattr(
        "ki_dev.runner.planning.flow_digest", lambda _flow: "anders"
    )
    result = runner.invoke(app, ["step", "x-1"])
    assert result.exit_code == 2
    assert "anderen Ablaufstand; mit --step neu" in result.stderr
    again = runner.invoke(app, ["step", "x-1", "--step", "map"])
    assert again.exit_code == 0, again.stderr
    assert load_state("x-1").state == "map"


def test_continue_rejects_further_options(bd, project):
    project()
    result = runner.invoke(app, ["step", "x-1", "--next-turn"])
    assert result.exit_code == 2


# --- Eine Antwort gilt nur für ihren Versuch (qu7.3, qu7.4) -----------


def _answer_file(tmp_path, without=(), **fields):
    value = json.loads(PASS_ANSWER) | fields
    for name in without:
        del value[name]
    path = tmp_path / "antwort.json"
    path.write_text(json.dumps(value))
    return [
        "step",
        "x-1",
        "--step",
        "review",
        "--next-turn",
        "--decision-file",
        str(path),
    ]


def _reviewed(project):
    root = project()
    review = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert review.exit_code == 0, review.stderr
    return root, review.stdout


def test_answer_without_attempt_is_refused_and_changes_nothing(
    bd, project, tmp_path
):
    _reviewed(project)
    before = load_state("x-1")
    result = runner.invoke(app, _answer_file(tmp_path, ("attempt",)))
    assert result.exit_code == 2
    assert "attempt: fehlt" in result.stderr
    assert load_state("x-1") == before


def test_foreign_attempt_is_refused_and_changes_nothing(
    bd, project, tmp_path
):
    _reviewed(project)
    before = load_state("x-1")
    result = runner.invoke(
        app, _answer_file(tmp_path, attempt="y-9:1")
    )
    assert result.exit_code == 2
    assert "nicht zum wartenden Versuch" in result.stderr
    assert load_state("x-1") == before


def test_old_answer_is_refused_after_a_new_preflight(
    bd, project, tmp_path
):
    """Review-Übergabe 1, Antwort PASS; der Stand hat sich geändert:
    PASS führt zum neuen Vorlauf und zur Review-Übergabe 2. Dieselbe
    Antwort gehört zu Versuch 1: Exit 2, kein finished."""
    root, first = _reviewed(project)
    attempt_one = attempt_of(first)
    (root / "neu.py").write_text("x = 1\n")
    second = runner.invoke(app, _answer_file(tmp_path))
    assert second.exit_code == 0, second.stderr
    assert attempt_of(second.stdout) != attempt_one
    assert load_state("x-1").state == "implement.review"
    again = runner.invoke(app, _answer_file(tmp_path))
    assert again.exit_code == 2
    assert "nicht zum wartenden Versuch" in again.stderr
    assert load_state("x-1").state == "implement.review"
    fresh = runner.invoke(
        app, _answer_file(tmp_path, attempt=attempt_of(second.stdout))
    )
    assert fresh.exit_code == 0, fresh.stderr
    assert load_state("x-1").state == "finished"


def test_old_answer_is_refused_after_a_correction_round(
    bd, project, tmp_path
):
    _reviewed(project)
    fix = _answer_file(
        tmp_path,
        event="fix",
        detail="Test fehlt",
        requirement_ref="AC1",
    )
    routed = runner.invoke(app, fix)
    assert routed.exit_code == 0, routed.stderr
    follow_up = runner.invoke(
        app, ["step", "x-1", "--step", "review", "--next-turn"]
    )
    assert follow_up.exit_code == 0, follow_up.stderr
    assert load_state("x-1").state == "implement.review"
    old = runner.invoke(app, _answer_file(tmp_path))
    assert old.exit_code == 2
    assert "nicht zum wartenden Versuch" in old.stderr
    assert load_state("x-1").state == "implement.review"
    attempt = attempt_of(follow_up.stdout)
    fresh = runner.invoke(
        app, _answer_file(tmp_path, attempt=attempt)
    )
    assert fresh.exit_code == 0, fresh.stderr
    assert load_state("x-1").state == "finished"


@pytest.mark.parametrize(
    ("first_args", "rejected_args", "expected_state"),
    [
        (["--step", "implement"], ["--step", "implement"], "implement"),
        (
            ["--step", "map"],
            ["--step", "review", "--review-of", "map"],
            "map",
        ),
    ],
)
def test_overlong_handoff_preserves_checkpoint_and_attempt(
    bd,
    project,
    step_state_root,
    first_args,
    rejected_args,
    expected_state,
):
    root = project()
    first = runner.invoke(app, ["step", "x-1", *first_args])
    assert first.exit_code == 0, first.stderr
    assert attempt_of(first.stdout) == "x-1:1"
    before = load_state("x-1")
    events = _events(step_state_root)
    config = root / "pyproject.toml"
    original = config.read_text()
    config.write_text("[tool.ki-dev.handoff]\nbase_max_chars = 1\n")

    rejected = runner.invoke(app, ["step", "x-1", *rejected_args])
    assert rejected.exit_code == 2
    assert "base_max_chars" in rejected.stderr
    assert load_state("x-1") == before
    assert load_state("x-1").state == expected_state
    assert _events(step_state_root) == events

    config.write_text(original)
    retry = runner.invoke(app, ["step", "x-1", *rejected_args])
    assert retry.exit_code == 0, retry.stderr
    assert attempt_of(retry.stdout) == "x-1:2"
