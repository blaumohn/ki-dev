import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ki_dev import beads_reader
from ki_dev.cli import app
from ki_dev.handoff import Step

runner = CliRunner()

NON_REVIEW_STEPS = [step for step in Step if step is not Step.REVIEW]

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

    real_run = subprocess.run

    def fake(argv, **kwargs):
        if not argv or argv[0] != "bd":
            # Nur bd faken; git/Vorlauf-Prüfbefehle der Review-Tests
            # laufen echt (beads_reader.subprocess ist dasselbe
            # Modulobjekt wie subprocess, das Patchen wirkt global).
            return real_run(argv, **kwargs)
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


@pytest.mark.parametrize("step", NON_REVIEW_STEPS)
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


def test_build_works_without_metadata(bd):
    bead = {k: v for k, v in FULL.items() if k != "metadata"}
    bd.state["stdout"] = json.dumps([bead])
    assert (
        runner.invoke(
            app, ["handoff", "x-1", "--step", "build"]
        ).exit_code
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


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True
    )


def _preflight_project(
    tmp_path: Path, *, checks: str, corrections: str = "[]"
) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "README.md").write_text("x\n")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-q", "-m", "base")
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ki-dev.handoff.preflight]\n"
        f"corrections = {corrections}\n"
        f"checks = {checks}\n"
    )
    return tmp_path


def _command(name: str, code: str, timeout_s: float = 5.0) -> str:
    py = json.dumps(sys.executable)
    return (
        f'{{name = "{name}", argv = [{py}, "-c", {json.dumps(code)}], '
        f"timeout_s = {timeout_s}}}"
    )


def test_review_preflight_success_runs_checks_and_appends_report(
    bd, tmp_path, monkeypatch
):
    _preflight_project(
        tmp_path, checks=f"[{_command('ok', 'print(1)')}]"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["handoff", "x-1", "--step", "review"])
    assert result.exit_code == 0
    assert result.stdout.startswith("Schritt: review\n")
    assert "PRUEFBERICHT git=" in result.stdout
    assert "- ok: PASS" in result.stdout
    assert result.stderr == ""
    artifacts = list(
        (tmp_path / ".local" / "handoff" / "preflight").glob("*.json")
    )
    assert len(artifacts) == 1
    assert json.loads(artifacts[0].read_text())["valid"] is True


def test_review_preflight_check_failure_exits_1_without_handoff(
    bd, tmp_path, monkeypatch
):
    fail_code = "import sys; sys.exit(1)"
    _preflight_project(
        tmp_path, checks=f"[{_command('fails', fail_code)}]"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["handoff", "x-1", "--step", "review"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Vorlauf ohne Review-Übergabe" in result.stderr
    assert "fails: FAIL" in result.stderr
    assert ".local/handoff/preflight" in result.stderr


def test_review_preflight_correction_failure_stops_before_checks(
    bd, tmp_path, monkeypatch
):
    _preflight_project(
        tmp_path,
        corrections=(
            f"[{_command('bad-correction', 'import sys; sys.exit(3)')}]"
        ),
        checks=f"[{_command('never-runs', 'raise SystemExit(1)')}]",
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["handoff", "x-1", "--step", "review"])
    assert result.exit_code == 1
    assert "bad-correction: FAIL" in result.stderr
    assert "never-runs: OMITTED" in result.stderr


def test_review_preflight_reports_passed_correction_after_check_fails(
    bd, tmp_path, monkeypatch
):
    """Eine erfolgreiche Korrektur kann den Arbeitsbaum bereits
    veraendert haben; der Reparaturbefund darf sie nicht ausblenden,
    nur weil ein spaeterer Check scheitert."""
    _preflight_project(
        tmp_path,
        corrections=f"[{_command('good-correction', 'print(1)')}]",
        checks=(f"[{_command('fails', 'import sys; sys.exit(1)')}]"),
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["handoff", "x-1", "--step", "review"])
    assert result.exit_code == 1
    assert "good-correction: PASS" in result.stderr
    assert "fails: FAIL" in result.stderr


def test_review_preflight_git_failure_is_reported_without_traceback(
    bd, tmp_path, monkeypatch
):
    """Kein Git-Repository am cwd: der Fingerprint kann nicht gebildet
    werden. Das muss ein kurzer Reparaturbefund mit Exit 1 sein, kein
    unbehandelter Traceback."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ki-dev.handoff.preflight]\n"
        "corrections = []\n"
        f"checks = [{_command('ok', 'print(1)')}]\n"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["handoff", "x-1", "--step", "review"])
    # Ein kontrolliertes _fail() endet als SystemExit ueber typer.Exit;
    # ein unbehandelter CalledProcessError waere eine andere
    # Exception-Klasse und keine saubere Reparaturmeldung.
    assert type(result.exception) is SystemExit
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Vorlauf-Ausführungsfehler" in result.stderr


def test_review_without_preflight_config_exits_2(
    bd, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["handoff", "x-1", "--step", "review"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Vorlauf-Konfiguration ungültig" in result.stderr


def test_review_validates_bead_before_preflight_config(
    bd, tmp_path, monkeypatch
):
    """Kein pyproject.toml am cwd noetig, wenn der Bead bereits formal
    unvollstaendig ist: Bead-Validierung geht der Konfiguration vor."""
    bd.state["stdout"] = json.dumps(
        [{k: v for k, v in FULL.items() if k != "design"}]
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["handoff", "x-1", "--step", "review"])
    assert result.exit_code == 2
    assert "design" in result.stderr
    assert "Vorlauf-Konfiguration" not in result.stderr
