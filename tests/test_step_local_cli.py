"""ki-dev step local: freie lokale Übergabe ohne Bead und ohne bd."""

import shutil
from functools import partial
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ki_dev.cli import app
from ki_dev.flow.planning import load_planning_flow
from ki_dev.ops.context import beads_reader
from ki_dev.ops.context.bead_input import BeadInput
from ki_dev.ops.context.contract import Step
from ki_dev.ops.context.guidelines import GUIDELINE_SOURCES
from tests.guideline_fixtures import write_guidelines
from tests.turn_helpers import (
    render_base_handoff as _render_base_handoff,
)

FLOW = load_planning_flow()
render_base_handoff = partial(_render_base_handoff, flow=FLOW)

runner = CliRunner()
REPO = Path(__file__).resolve().parents[1]
LOCAL = ["step", "local"]


@pytest.fixture
def offline(tmp_path, monkeypatch):
    """Arbeitsverzeichnis ohne bd im PATH; jeder Beads-Zugriff schlägt
    den Test fehl."""
    empty = tmp_path / "leer"
    empty.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    monkeypatch.chdir(work)

    def no_bd(*args, **kwargs):
        raise AssertionError("local darf bd nicht aufrufen")

    monkeypatch.setattr(beads_reader, "read_issue", no_bd)
    return work


def real_sources(work):
    shutil.copytree(REPO / "docs/policies", work / "docs/policies")


def test_local_runs_without_bead_db_or_bd_on_path(offline):
    write_guidelines(offline)
    result = runner.invoke(app, LOCAL)
    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("Schritt: local\n")
    assert "ki-dev step BEAD_ID --step STEP" in result.stdout
    assert result.stderr == ""


def test_local_gives_only_common_sections_once_per_source(offline):
    write_guidelines(offline)
    out = runner.invoke(app, LOCAL).stdout
    for index, source in enumerate(GUIDELINE_SOURCES):
        assert f"--- {source.path}#common ---" in out
        assert out.count(f"- Q{index}:shared") == 1
        assert f"- Q{index}:implement-task" not in out
        assert f"- Q{index}:implement-review" not in out


def test_local_carries_former_entry_texts_without_claim_or_close(
    offline,
):
    real_sources(offline)
    out = runner.invoke(app, LOCAL).stdout
    for expected in (
        "bd show ID",
        "bd ready",
        "bd prime",
        "./.venv/bin/python -m pytest",
        "unittest discover",
        "## Manueller Handoff",
        "Keine Fortschrittskommentare.",
        "## Verbrauchsmessung: Sitzungsdaten sparsam untersuchen",
        "scripts/render-guidelines.py",
        "docs/architecture/tokenmessung-estimatoren.de.md",
        "weder committen noch pushen",
    ):
        assert expected in out
    # Keine Aufforderung zum Beanspruchen oder Schließen, keine
    # privaten absoluten Pfade als Voraussetzung.
    assert "bd update" not in out
    assert "bd close" not in out
    assert "/home/" not in out


@pytest.mark.parametrize(
    "extra",
    [
        ["--step", "implement"],
        ["--step", "review", "--review-of", "implement"],
        ["--step", "review", "--preflight-args", "tests=-k x"],
        ["--step", "review", "--next-turn"],
        ["--step", "review", "--next-turn", "--feedback-file", "-"],
        ["--agent", "codex"],
        ["--session", "abc"],
    ],
)
def test_local_rejects_mixing_with_other_forms(offline, extra):
    write_guidelines(offline)
    result = runner.invoke(app, [*LOCAL, *extra])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "local lässt sich nicht" in result.stderr


def test_missing_source_is_exit_1(offline):
    write_guidelines(offline)
    (offline / GUIDELINE_SOURCES[2].path).unlink()
    result = runner.invoke(app, LOCAL)
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "arbeitsregeln" in result.stderr


def test_invalid_source_is_exit_2(offline):
    write_guidelines(offline)
    (offline / GUIDELINE_SOURCES[2].path).write_text("[1, 2")
    result = runner.invoke(app, LOCAL)
    assert result.exit_code == 2
    assert result.stdout == ""


def _limit(work, value):
    (work / "pyproject.toml").write_text(
        f"[tool.ki-dev.handoff]\nbase_max_chars = {value}\n"
    )


def test_base_limit_counts_only_base_equal_ok_over_rejected(offline):
    write_guidelines(offline)
    full = runner.invoke(app, LOCAL).stdout
    base = full.split("\nLEITLINIEN", 1)[0]
    _limit(offline, len(base))
    assert runner.invoke(app, LOCAL).stdout == full
    _limit(offline, len(base) - 1)
    result = runner.invoke(app, LOCAL)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Basisübergabe zu lang" in result.stderr


def test_invalid_limit_config_is_exit_2(offline):
    write_guidelines(offline)
    _limit(offline, "true")
    result = runner.invoke(app, LOCAL)
    assert result.exit_code == 2
    assert result.stdout == ""


def test_bead_handoff_no_longer_points_to_agents_md():
    issue = BeadInput(
        id="x-1",
        title="T",
        description="D",
        design="S",
        acceptance_criteria="A",
    )
    text = render_base_handoff(issue, Step.IMPLEMENT)
    assert "AGENTS.md" not in text
    assert "bd show BEAD_ID" in text
