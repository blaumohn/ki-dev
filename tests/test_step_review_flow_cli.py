"""``ki-dev -f ABLAUF step`` auf dem Review-Muster
(ki-dev-ablauf-ige.9): zustandslos, die Antworten je Zustand im
Aufruf, Deutung durch die Ops des Pakets, Eingaben mit Herkunft."""

from __future__ import annotations

import json

import pytest

from tests.fake_bd_command import BdScript
from tests.guideline_fixtures import write_guidelines
from tests.test_step_cli import FULL, _command, _preflight_project
from tests.turn_helpers import flow_step

PREFLIGHT = {
    "event": "checks_passed",
    "facts": ["full_checks"],
    "report": None,
    "finding": None,
}


@pytest.fixture
def project(monkeypatch, tmp_path, tmp_path_factory):
    BdScript(
        tmp_path_factory.mktemp("bd"), stdout=json.dumps([FULL])
    ).install(monkeypatch)
    write_guidelines(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _file(project, name: str, value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value)
    (project / name).write_text(text, encoding="utf-8")
    return name


def _verdict(event: str, ref: str | None = None, **extra) -> dict:
    return {
        "event": event,
        "detail": "Befund",
        "requirement_ref": ref,
        **extra,
    }


# --- map: fix → correction, PASS ------------------------------------


def test_map_review_fix_hands_the_finding_to_the_writer(project):
    _file(project, "review.json", _verdict("fix", "AC1"))
    result = flow_step(
        "map", "x-1", "map.review", "map.review=review.json"
    )
    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("Empfänger: Umsetzer")
    assert "Review-Befund (fix, CHANGES, AC1): Befund" in result.stdout
    assert "- fix → map.correction" in result.stdout


def test_map_review_pass_ends_with_the_next_flow(project):
    _file(project, "review.json", _verdict("PASS"))
    result = flow_step(
        "map", "x-1", "map.review", "map.review=review.json"
    )
    assert result.exit_code == 0, result.stderr
    assert "Review-Urteil PASS (PASS)" in result.stdout
    assert "`ki-dev -f graph step x-1 graph`" in result.stdout


def test_same_answer_gives_same_output_and_stores_nothing(project):
    _file(project, "review.json", _verdict("fix", "AC1"))
    before = sorted(p.name for p in project.iterdir())
    args = ("map", "x-1", "map.review", "map.review=review.json")
    assert flow_step(*args).stdout == flow_step(*args).stdout
    assert sorted(p.name for p in project.iterdir()) == before


def test_correction_needs_the_verdict_from_the_review(project):
    result = flow_step("map", "x-1", "map.correction")
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "map.correction braucht verdict (aus map.review" in (
        result.stderr
    )
    _file(project, "review.json", _verdict("fix", "AC1"))
    supplied = flow_step(
        "map", "x-1", "map.correction", "map.review=review.json"
    )
    assert supplied.exit_code == 0, supplied.stderr
    assert "Review-Befund (fix" in supplied.stdout


def test_correction_done_sends_the_follow_up_with_feedback(project):
    _file(project, "done.json", {"feedback": "Abschnitt ergänzt"})
    result = flow_step(
        "map", "x-1", "map.correction", "map.correction=done.json"
    )
    assert result.exit_code == 0, result.stderr
    assert "Erneute Prüfung nach Korrekturen" in result.stdout
    assert "| Abschnitt ergänzt" in result.stdout


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        ("kein json", "kein JSON"),
        ({"feedback": " "}, "feedback: pattern"),
        ({"feedback": "x" * 601}, "feedback: maxLength"),
        ({"anders": 1}, "additionalProperties"),
    ],
)
def test_invalid_done_answer_exits_2(project, answer, message):
    _file(project, "done.json", answer)
    result = flow_step(
        "map", "x-1", "map.correction", "map.correction=done.json"
    )
    assert result.exit_code == 2
    assert message in result.stderr
    assert "xxx" not in result.stderr


def test_invalid_review_answer_exits_2_without_raw_value(project):
    _file(project, "review.json", {"event": "GEHEIM", "detail": ""})
    result = flow_step(
        "map", "x-1", "map.review", "map.review=review.json"
    )
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Review-Antwort ungültig" in result.stderr
    assert "GEHEIM" not in result.stderr


def test_human_decision_takes_its_edge(project):
    _file(project, "entscheidung.json", {"event": "correct"})
    _file(project, "review.json", _verdict("decision"))
    result = flow_step(
        "map",
        "x-1",
        "map.decision",
        "map.decision=entscheidung.json",
        "map.review=review.json",
    )
    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("Empfänger: Umsetzer")
    bad = _file(project, "falsch.json", {"event": "PASS"})
    refused = flow_step(
        "map", "x-1", "map.decision", f"map.decision={bad}"
    )
    assert refused.exit_code == 2
    assert "Antwort in map.decision ungültig" in refused.stderr


# --- implement_review: Vorlauf, Wächter, Eingaben -------------------


def test_pass_needs_the_preflight_facts_as_input(project):
    _file(project, "review.json", _verdict("PASS"))
    result = flow_step(
        "implement_review",
        "x-1",
        "implement.review",
        "implement.review=review.json",
    )
    assert result.exit_code == 2
    assert (
        "implement.review --PASS--> braucht facts "
        "(aus implement.preflight" in result.stderr
    )


def test_pass_with_preflight_answer_finishes(project):
    _file(project, "review.json", _verdict("PASS"))
    _file(project, "vorlauf.json", PREFLIGHT)
    result = flow_step(
        "implement_review",
        "x-1",
        "implement.review",
        "implement.review=review.json",
        "implement.preflight=vorlauf.json",
    )
    assert result.exit_code == 0, result.stderr
    assert "Review-Urteil PASS" in result.stdout
    assert not (project / ".local").exists()


def test_pass_after_partial_run_is_refused_by_the_guard(project):
    _file(project, "review.json", _verdict("PASS"))
    _file(project, "vorlauf.json", PREFLIGHT | {"facts": []})
    result = flow_step(
        "implement_review",
        "x-1",
        "implement.review",
        "implement.review=review.json",
        "implement.preflight=vorlauf.json",
    )
    assert result.exit_code == 2
    assert "Ereignis PASS nicht erlaubt (Wächter full_checks)" in (
        result.stderr
    )


def test_invalid_preflight_answer_exits_2(project):
    _file(project, "review.json", _verdict("PASS"))
    _file(project, "vorlauf.json", {"event": "checks_passed"})
    result = flow_step(
        "implement_review",
        "x-1",
        "implement.review",
        "implement.review=review.json",
        "implement.preflight=vorlauf.json",
    )
    assert result.exit_code == 2
    assert "Antwort von implement.preflight ungültig" in result.stderr


def test_review_handoff_needs_the_preflight_data(project):
    result = flow_step("implement_review", "x-1", "implement.review")
    assert result.exit_code == 2
    assert "braucht facts (aus implement.preflight" in result.stderr


def test_written_answer_runs_the_preflight_into_the_review(project):
    _preflight_project(
        project, checks=f"[{_command('tests', 'print(1)')}]"
    )
    _file(project, "done.json", {})
    result = flow_step(
        "implement_review", "x-1", "implement", "implement=done.json"
    )
    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("Schritt: review\n")
    assert "- tests: PASS" in result.stdout
    assert "Vorlauf: tests läuft" in result.stderr


def test_review_control_becomes_options_for_the_next_call(project):
    _file(
        project,
        "review.json",
        _verdict(
            "fix", "AC1", preflight_skip={"tests": "nur Doku"}
        ),
    )
    (project / "pyproject.toml").write_text(
        "[tool.ki-dev.handoff.preflight]\n"
        "corrections = []\n"
        f"checks = [{_command('tests', 'print(1)')}]\n"
    )
    result = flow_step(
        "implement_review",
        "x-1",
        "implement.review",
        "implement.review=review.json",
    )
    assert result.exit_code == 0, result.stderr
    assert "an den step-Aufruf mit Vorlauf anhängen" in result.stdout
    assert "--preflight-skip 'tests=nur Doku'" in result.stdout
