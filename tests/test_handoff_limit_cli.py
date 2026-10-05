"""Basisgrenze in der CLI: beide Formen, offline, ohne Modelle."""

import json
import re
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ki_dev.cli import app
from ki_dev.handoff import Step, render_guideline_block
from ki_dev.handoff_cli import HELP
from ki_dev.handoff_guidelines import select_guidelines
from ki_dev.handoff_guidelines_source import load_guidelines
from ki_dev.handoff_limit import MAX_DIAGNOSIS_CHARS
from tests.codex_session_fixtures import (
    SECRET,
    dialog,
    write_session,
)
from tests.fake_bd import FakeBd
from tests.fake_bd_command import BdScript
from tests.guideline_fixtures import write_guidelines

runner = CliRunner()
ROOT = Path(__file__).resolve().parent.parent
TITLE = "Titel GEHEIMER-TITELTEXT"
TABLE = "[tool.ki-dev.handoff]\n"
FULL = {
    "id": "x-1",
    "title": TITLE,
    "description": "Beschreibung",
    "design": "Design",
    "acceptance_criteria": "AC",
    "metadata": {"handoff": {"source_refs": ["a.md#L1-L2"]}},
}


def _config(root: Path, text: str) -> None:
    (root / "pyproject.toml").write_text(text, encoding="utf-8")


def _limit(root: Path, value) -> None:
    _config(root, f"{TABLE}base_max_chars = {value}\n")


@pytest.fixture(autouse=True)
def project(tmp_path, monkeypatch):
    write_guidelines(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def bd(monkeypatch, tmp_path_factory):
    fake = BdScript(
        tmp_path_factory.mktemp("bd"), stdout=json.dumps([FULL])
    )
    fake.install(monkeypatch)
    return fake


def _handoff(*args: str):
    return runner.invoke(app, ["step", "x-1", *args])


def _measured_base(project, *args: str) -> int:
    """Zeichenzahl der Basis aus der Diagnose einer Übergröße."""
    _limit(project, 1)
    result = _handoff(*args)
    assert result.exit_code == 2
    return int(re.search(r"(\d+) Zeichen, Grenze", result.stderr)[1])


# --- Bead-Form ------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["--step", "map"],
        ["--step", "graph"],
        ["--step", "materialize"],
        ["--step", "build"],
        ["--step", "review", "--review-of", "map"],
        ["--step", "review", "--review-of", "materialize"],
    ],
)
def test_overlong_base_exits_2_with_empty_stdout(bd, project, args):
    _limit(project, 1)
    result = _handoff(*args)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert re.search(r"\d+ Zeichen, Grenze 1 ", result.stderr)
    assert "base_max_chars" in result.stderr
    assert len(result.stderr) <= MAX_DIAGNOSIS_CHARS + 1
    assert "GEHEIMER-TITELTEXT" not in result.stderr


def test_boundary_equal_is_allowed_and_one_less_is_rejected(
    bd, project
):
    size = _measured_base(project, "--step", "build")
    _limit(project, size)
    ok = _handoff("--step", "build")
    assert ok.exit_code == 0
    assert ok.stdout.index("\nLEITLINIEN") == size
    _limit(project, size - 1)
    assert _handoff("--step", "build").exit_code == 2


def test_guidelines_do_not_count_to_the_base(bd, project):
    size = _measured_base(project, "--step", "build")
    _limit(project, size)
    text = _handoff("--step", "build").stdout
    assert text.startswith("Schritt: build\n")
    assert len(text) > size


def test_default_4000_applies_without_configuration(bd, project):
    assert not (project / "pyproject.toml").exists()
    assert _handoff("--step", "build").exit_code == 0
    bd.state["stdout"] = json.dumps([FULL | {"title": "T" * 6000}])
    assert _handoff("--step", "build").exit_code == 2


def test_epic_hint_counts_and_is_named_by_index(bd, project):
    epic = {
        "id": "ep",
        "title": "E",
        "description": "D",
        "issue_type": "epic",
        "metadata": {"handoff": {"epic_context": "Epic-Text " * 50}},
    }
    child = FULL | {
        "dependencies": [
            {"id": "ep", "dependency_type": "parent-child"}
        ]
    }
    bd.state["graph"] = {"x-1": child, "ep": epic}
    bd.state["stdout"] = ""
    _limit(project, 1)
    result = _handoff("--step", "build")
    assert result.exit_code == 2
    assert "epic_context[0]" in result.stderr
    assert "Epic-Text" not in result.stderr


@pytest.mark.parametrize(
    "text",
    [
        "base_max_chars = 0",
        "base_max_chars = -3",
        "base_max_chars = true",
        "base_max_chars = 4000.0",
        'base_max_chars = "4000"',
        "base_max_chars = [1]",
    ],
)
def test_invalid_value_exits_2_before_reading_beads(bd, project, text):
    _config(project, f"{TABLE}{text}\n")
    result = _handoff("--step", "build")
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "tool.ki-dev.handoff.base_max_chars" in result.stderr
    assert bd.calls == []


@pytest.mark.parametrize(
    "text", ["tool = 7\n", "[tool.ki-dev]\nhandoff = 1\n", "[kaputt\n"]
)
def test_wrong_table_or_defective_toml_exits_2(bd, project, text):
    _config(project, text)
    result = _handoff("--step", "build")
    assert result.exit_code == 2
    assert result.stdout == ""
    assert bd.calls == []


def test_unreadable_configuration_exits_1(bd, project):
    (project / "pyproject.toml").mkdir()
    result = _handoff("--step", "build")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert bd.calls == []


def test_non_default_valid_value_is_effective(bd, project):
    _limit(project, 9999)
    bd.state["stdout"] = json.dumps([FULL | {"title": "T" * 6000}])
    assert _handoff("--step", "build").exit_code == 0


# --- Build-Review: Grenze vor dem Vorlauf ---------------------------


def _review_project(project: Path, limit: int | str) -> Path:
    marker = project / "vorlauf-lief"
    code = f"open({str(marker)!r}, 'w').close()"
    argv = json.dumps([sys.executable, "-c", code])
    _config(
        project,
        f"{TABLE}base_max_chars = {limit}\n"
        "[tool.ki-dev.handoff.preflight]\n"
        "corrections = []\n"
        "[[tool.ki-dev.handoff.preflight.checks]]\n"
        f'name = "marker"\nargv = {argv}\ntimeout_s = 10\n',
    )
    return marker


def test_review_over_limit_blocks_before_any_preflight(bd, project):
    marker = _review_project(project, 1)
    for args in (
        ["--step", "review"],
        ["--step", "review", "--review-of", "build"],
    ):
        result = _handoff(*args)
        assert result.exit_code == 2
        assert result.stdout == ""
        assert "Vorlauf" not in result.stderr
        assert "Zeichen, Grenze 1" in result.stderr
    assert not marker.exists()
    assert not (project / ".local").exists()


def test_review_report_is_not_counted_and_guidelines_follow(
    bd, project
):
    marker = _review_project(project, 100000)
    full = _handoff("--step", "review").stdout
    size = full.index("PRUEFBERICHT")
    marker.unlink()
    _review_project(project, size)
    ok = _handoff("--step", "review")
    assert ok.exit_code == 0
    assert marker.exists()
    assert len(ok.stdout) > size
    marker.unlink()
    _review_project(project, size - 1)
    assert _handoff("--step", "review").exit_code == 2
    assert not marker.exists()


def _enlarge_guidelines(project: Path, filler: str) -> None:
    for path in (project / "docs" / "policies").glob("*.de.yaml"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for section in data["sections"]:
            section["text"] += "\n" + filler
        path.write_text(json.dumps(data), encoding="utf-8")


def test_review_base_at_limit_keeps_large_report_and_guidelines(
    bd, project
):
    """AC2: Basis exakt 4000, Bericht und mehr als 17000 Zeichen
    Leitlinien vollständig und nicht mitgezählt."""
    filler = "F" * 6000
    _enlarge_guidelines(project, filler)
    _review_project(project, 4000)
    bd.state["stdout"] = json.dumps([FULL | {"title": "x"}])
    short = _handoff("--step", "review").stdout.index("PRUEFBERICHT")
    title = "x" + "ä" * (4000 - short)
    bd.state["stdout"] = json.dumps([FULL | {"title": title}])
    result = _handoff("--step", "review")
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    assert out.index("PRUEFBERICHT") == 4000
    for line in (
        "PRUEFBERICHT vorlauf-start=",
        "- marker: PASS",
        "Vollständig: .local/handoff/preflight/",
        "Hinweis: Der Zeitpunkt dient",
    ):
        assert line in out[4000:]
    sections = select_guidelines(
        load_guidelines(project), Step.REVIEW, None
    )
    assert out.endswith(render_guideline_block(sections))
    assert out.count(filler) == len(sections)
    assert all(section.text in out for section in sections)
    assert sum(len(section.text) for section in sections) >= 17000


def test_review_invalid_configuration_blocks_before_preflight(
    bd, project
):
    marker = _review_project(project, "0")
    assert _handoff("--step", "review").exit_code == 2
    assert not marker.exists()
    assert bd.calls == []


# --- --next-turn bleibt unverändert ---------------------------------


@pytest.mark.parametrize("value", ["1", "0", '"x"'])
def test_next_turn_ignores_the_base_limit(bd, project, value):
    _limit(project, value)
    result = _handoff(
        "--step", "review", "--review-of", "materialize", "--next-turn"
    )
    assert result.exit_code == 0
    assert "Reviewziel: materialize" in result.stdout


# --- Hilfe und Dokumentation ----------------------------------------


def test_help_and_doc_explain_the_limit():
    for text in (HELP, (ROOT / "docs/handoff.de.md").read_text()):
        assert "base_max_chars" in text
        assert "4000" in text


# --- Sitzungsform ---------------------------------------------------

SID = "0199aaaa-bbbb-cccc-dddd-eeeeffff0001"
MAP = ["step", "map", "--agent", "codex", "--session", SID]


@pytest.fixture
def session(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    write_session(sessions, SID, dialog(2))
    fake = FakeBd(tmp_path, SECRET)
    fake.install(monkeypatch)
    monkeypatch.setenv("KI_DEV_CODEX_SESSIONS_DIR", str(sessions))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return fake


def _artifacts(project: Path) -> list[Path]:
    return sorted((project / ".local").rglob("*.jsonl"))


@pytest.mark.parametrize(
    "text", ["base_max_chars = 0", "base_max_chars = 1.5", "[kaputt"]
)
def test_map_invalid_configuration_stops_before_any_write(
    session, project, text
):
    _config(project, f"{TABLE}{text}\n")
    result = runner.invoke(app, MAP)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert _artifacts(project) == []
    assert session.commands() == []


def test_map_unreadable_configuration_exits_1_before_any_write(
    session, project
):
    (project / "pyproject.toml").mkdir()
    result = runner.invoke(app, MAP)
    assert result.exit_code == 1
    assert _artifacts(project) == []
    assert session.commands() == []


def test_map_overlong_base_keeps_idempotent_artifacts(session, project):
    _limit(project, 1)
    result = runner.invoke(app, MAP)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert len(result.stderr) <= MAX_DIAGNOSIS_CHARS + 1
    assert "Lesehinweis" in result.stderr
    assert "bleiben bestehen" in result.stderr
    [artifact] = _artifacts(project)
    [bead] = session.rows
    content = artifact.read_text()
    _limit(project, 4000)
    again = runner.invoke(app, MAP)
    assert again.exit_code == 0, again.stderr
    assert "Quelle: normalisiertes Transkript" in again.stdout
    assert _artifacts(project) == [artifact]
    assert artifact.read_text() == content
    assert session.rows == [bead]


def test_map_hint_counts_to_the_base(session, project):
    _limit(project, 1)
    result = runner.invoke(app, MAP)
    size = int(re.search(r"(\d+) Zeichen", result.stderr)[1])
    _limit(project, size)
    ok = runner.invoke(app, MAP)
    assert ok.exit_code == 0
    assert "Quelle: normalisiertes Transkript" in ok.stdout
    _limit(project, size - 1)
    assert runner.invoke(app, MAP).exit_code == 2
