import json
import subprocess

import pytest
from typer.testing import CliRunner

from ki_dev import beads_reader
from ki_dev.cli import app
from ki_dev.handoff import Step

runner = CliRunner()

FULL = {
    "id": "x-1",
    "title": "Titel [red]rot[/red]",
    "description": "Beschreibung",
    "design": "Design",
    "acceptance_criteria": "AC",
    "notes": "GEHEIME NOTIZ",
    "comments": [{"text": "GEHEIMER KOMMENTAR"}],
    "metadata": {"handoff": {"source_refs": ["a.md#L1-L2", "bd:k"]}},
}


@pytest.fixture
def bd(monkeypatch):
    calls = []
    state = {
        "stdout": json.dumps([FULL]),
        "returncode": 0,
        "raises": None,
    }

    def fake(argv, **kwargs):
        calls.append(argv)
        if state["raises"]:
            raise state["raises"]
        return subprocess.CompletedProcess(
            argv, state["returncode"], state["stdout"], "boese\n" * 30
        )

    monkeypatch.setattr(beads_reader.subprocess, "run", fake)
    fake.calls = calls
    fake.state = state
    return fake


@pytest.mark.parametrize("step", list(Step))
def test_every_step_prints_plain_handoff(bd, step):
    result = runner.invoke(
        app, ["handoff", "x-1", "--step", step.value]
    )
    assert result.exit_code == 0
    assert result.stdout.startswith(f"Schritt: {step.value}\n")
    assert "Bead: x-1 - Titel [red]rot[/red]\n" in result.stdout
    assert "\x1b" not in result.stdout
    assert "GEHEIME" not in result.stdout
    assert result.stderr == ""
    assert bd.calls == [["bd", "--readonly", "show", "x-1", "--json"]]


def test_same_input_gives_same_output(bd):
    args = ["handoff", "x-1", "--step", "review"]
    assert (
        runner.invoke(app, args).stdout
        == runner.invoke(app, args).stdout
    )


def test_long_lines_are_not_wrapped(bd):
    bd.state["stdout"] = json.dumps([FULL | {"title": "T" * 300}])
    result = runner.invoke(
        app, ["handoff", "x-1", "--step", "build"], terminal_width=40
    )
    assert f"Bead: x-1 - {'T' * 300}\n" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ["handoff"],
        ["handoff", "x-1"],
        ["handoff", "--step", "map"],
        ["handoff", "x-1", "--step", "unbekannt"],
        ["handoff", "x-1", "--step", ""],
        ["handoff", "", "--step", "map"],
        ["handoff", "-x", "--step", "map"],
    ],
)
def test_incomplete_or_invalid_call_exits_2_without_bd(bd, args):
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert bd.calls == []


def test_help_is_german_and_lists_steps_and_fields(bd):
    result = runner.invoke(app, ["handoff", "--help"])
    assert result.exit_code == 0
    for text in (
        "BEAD_ID",
        "map",
        "graph",
        "materialize",
        "build",
        "review",
        "metadata.handoff.source_refs",
        "acceptance_criteria",
        "design",
        "Fortsetzung von Hand",
    ):
        assert text in result.output
    assert bd.calls == []


@pytest.mark.parametrize("step", ["map", "graph", "materialize"])
def test_missing_source_refs_block_only_reference_steps(bd, step):
    bead = {k: v for k, v in FULL.items() if k != "metadata"}
    bd.state["stdout"] = json.dumps([bead])
    result = runner.invoke(app, ["handoff", "x-1", "--step", step])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "metadata.handoff.source_refs" in result.stderr


@pytest.mark.parametrize("step", ["build", "review"])
def test_build_review_work_without_metadata(bd, step):
    bead = {k: v for k, v in FULL.items() if k != "metadata"}
    bd.state["stdout"] = json.dumps([bead])
    assert (
        runner.invoke(app, ["handoff", "x-1", "--step", step]).exit_code
        == 0
    )


def test_missing_contract_fields_are_named_on_stderr(bd):
    bead = FULL | {"design": "", "acceptance_criteria": 5}
    bd.state["stdout"] = json.dumps([bead])
    result = runner.invoke(app, ["handoff", "x-1", "--step", "build"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "acceptance_criteria" in result.stderr
    assert "design" in result.stderr


def test_markup_like_field_path_is_printed_literally(bd):
    bd.state["stdout"] = json.dumps(
        [FULL | {"metadata": {"handoff": {"source_refs": [3]}}}]
    )
    result = runner.invoke(app, ["handoff", "x-1", "--step", "map"])
    assert "metadata.handoff.source_refs[0]" in result.stderr


@pytest.mark.parametrize(
    "change",
    [
        {"stdout": "kein json"},
        {"stdout": json.dumps([FULL, FULL])},
        {"stdout": json.dumps([FULL | {"id": "andere"}])},
        {"returncode": 1},
        {"raises": subprocess.TimeoutExpired(["bd"], 10)},
        {"raises": FileNotFoundError("bd")},
    ],
)
def test_adapter_errors_exit_1_without_raw_output(bd, change):
    bd.state.update(change)
    result = runner.invoke(app, ["handoff", "x-1", "--step", "map"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Beads-Lesefehler" in result.stderr
    assert "GEHEIME" not in result.stderr
    assert "boese" not in result.stderr
    assert len(result.stderr) < 300
