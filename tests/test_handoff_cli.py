import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ki_dev import beads_reader, handoff_preflight
from ki_dev.cli import app
from ki_dev.handoff import Step
from tests.fake_bd_command import BdScript
from tests.guideline_fixtures import write_guidelines

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


@pytest.fixture(autouse=True)
def guideline_sources(tmp_path):
    # Tests mit chdir(tmp_path) brauchen gültige Leitlinienquellen.
    write_guidelines(tmp_path)


@pytest.fixture
def bd(monkeypatch, tmp_path_factory):
    fake = BdScript(
        tmp_path_factory.mktemp("bd"),
        stdout=json.dumps([FULL]),
        stderr="boese\n" * 30,
    )
    fake.install(monkeypatch)
    return fake


@pytest.mark.parametrize("step", NON_REVIEW_STEPS)
def test_every_step_prints_plain_handoff(bd, step):
    result = runner.invoke(
        app, ["step", "x-1", "--step", step.value]
    )
    assert result.exit_code == 0
    assert result.stdout.startswith(f"Schritt: {step.value}\n")
    assert "Bead: x-1 - Titel [red]rot[/red]\n" in result.stdout
    assert "\x1b" not in result.stdout
    assert "GEHEIME" not in result.stdout
    assert result.stderr == ""
    assert bd.calls == [["bd", "--readonly", "show", "x-1", "--json"]]


def test_same_input_gives_same_output(bd):
    # Nicht review: dessen Bericht trägt einen Zeitstempel, und ohne
    # eigenes Projekt liefe der Vorlauf dieses Repos (pytest) rekursiv.
    args = ["step", "x-1", "--step", "build"]
    assert (
        runner.invoke(app, args).stdout
        == runner.invoke(app, args).stdout
    )


def test_missing_bead_names_id_on_stderr(bd):
    bd.state.update(
        returncode=1,
        stdout=json.dumps(
            {"error": "no issues found matching the provided IDs"}
        ),
    )
    result = runner.invoke(app, ["step", "x-1", "--step", "build"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert (
        result.stderr == "Beads-Lesefehler: Bead x-1 nicht gefunden\n"
    )


def test_long_lines_are_not_wrapped(bd):
    bd.state["stdout"] = json.dumps([FULL | {"title": "T" * 300}])
    result = runner.invoke(
        app, ["step", "x-1", "--step", "build"], terminal_width=40
    )
    assert f"Bead: x-1 - {'T' * 300}\n" in result.stdout


@pytest.mark.parametrize(
    "args",
    [
        ["step"],
        ["step", "x-1"],
        ["step", "--step", "map"],
        ["step", "x-1", "--step", "unbekannt"],
        ["step", "x-1", "--step", ""],
        ["step", "", "--step", "map"],
        ["step", "-x", "--step", "map"],
    ],
)
def test_incomplete_or_invalid_call_exits_2_without_bd(bd, args):
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert bd.calls == []


def test_help_explains_steps_and_shows_examples(bd):
    result = runner.invoke(app, ["step", "--help"])
    assert result.exit_code == 0
    for text in (
        "BEAD_ID",
        "map",
        "graph",
        "materialize",
        "build",
        "review",
        "Anforderungen aus Rohnotizen kartieren",
        "Vorgänge ableiten",
        "ausführungsreif beschreiben",
        "Auftrag umsetzen",
        "getrennten Sitzung prüfen",
        "BEISPIELE",
        "ki-dev step projekt-42 --step build > uebergabe.txt",
        "--review-of materialize",
        "--next-turn --feedback-file",
        "höchstens feedback_max_chars Zeichen",
        "tool.ki-dev.handoff;",
        "docs/handoff.de.md",
    ):
        assert text in result.output
    assert "ki-dev handoff" not in result.output
    assert bd.calls == []


@pytest.mark.parametrize(
    "args",
    [
        ["handoff", "x-1", "--step", "build"],
        ["handoff", "map", "--agent", "codex", "--session", "s"],
        ["handoff", "local"],
    ],
)
def test_former_handoff_command_is_gone_without_alias(bd, args):
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert bd.calls == []


@pytest.mark.parametrize("step", ["map", "graph", "materialize"])
def test_missing_source_refs_block_only_reference_steps(bd, step):
    bead = {k: v for k, v in FULL.items() if k != "metadata"}
    bd.state["stdout"] = json.dumps([bead])
    result = runner.invoke(app, ["step", "x-1", "--step", step])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "metadata.handoff.source_refs" in result.stderr


def test_build_works_without_metadata(bd):
    bead = {k: v for k, v in FULL.items() if k != "metadata"}
    bd.state["stdout"] = json.dumps([bead])
    assert (
        runner.invoke(
            app, ["step", "x-1", "--step", "build"]
        ).exit_code
        == 0
    )


def test_missing_contract_fields_are_named_on_stderr(bd):
    bead = FULL | {"design": "", "acceptance_criteria": 5}
    bd.state["stdout"] = json.dumps([bead])
    result = runner.invoke(app, ["step", "x-1", "--step", "build"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "acceptance_criteria" in result.stderr
    assert "design" in result.stderr


def test_markup_like_field_path_is_printed_literally(bd):
    bd.state["stdout"] = json.dumps(
        [FULL | {"metadata": {"handoff": {"source_refs": [3]}}}]
    )
    result = runner.invoke(app, ["step", "x-1", "--step", "map"])
    assert "metadata.handoff.source_refs[0]" in result.stderr


@pytest.mark.parametrize(
    "change",
    [
        {"stdout": "kein json"},
        {"stdout": json.dumps([FULL, FULL])},
        {"stdout": json.dumps([FULL | {"id": "andere"}])},
        {"returncode": 1},
        {"hang": True},
    ],
)
def test_adapter_errors_exit_1_without_raw_output(
    bd, change, monkeypatch
):
    monkeypatch.setattr(beads_reader, "BD_TIMEOUT_S", 0.5)
    bd.state.update(change)
    result = runner.invoke(app, ["step", "x-1", "--step", "map"])
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
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 0
    assert result.stdout.startswith("Schritt: review\n")
    assert "PRUEFBERICHT vorlauf-start=" in result.stdout
    assert "- ok: PASS" in result.stdout
    assert result.stderr == "Vorlauf: ok läuft (Timeout 5 s) …\n"
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
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Vorlauf ohne Review-Übergabe" in result.stderr
    assert "fails: FAIL" in result.stderr
    assert ".local/handoff/preflight" in result.stderr
    assert result.stderr.startswith("Vorlauf: fails läuft")


def test_review_preflight_repair_finding_names_artifact_file_once(
    bd, tmp_path, monkeypatch
):
    _preflight_project(
        tmp_path,
        checks=f"[{_command('fails', 'import sys; sys.exit(1)')}]",
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    (artifact,) = (tmp_path / ".local" / "handoff" / "preflight").glob(
        "*.json"
    )
    assert result.stderr.count("Vollständig:") == 1
    assert (
        f"Vollständig: .local/handoff/preflight/{artifact.name}"
        in result.stderr
    )


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
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
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
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 1
    assert "good-correction: PASS" in result.stderr
    assert "fails: FAIL" in result.stderr


def test_review_preflight_repair_hint_covers_fail_not_only_pass(
    bd, tmp_path, monkeypatch
):
    """Auch ein fehlgeschlagener Befehl kann den Arbeitsbaum bereits
    veraendert haben (z. B. ein Formatter, der eine Datei aendert und
    danach scheitert); der Hinweis darf nicht nur PASS erwaehnen."""
    _preflight_project(
        tmp_path,
        checks=f"[{_command('fails', 'import sys; sys.exit(1)')}]",
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 1
    assert "PASS wie" in result.stderr
    assert "FAIL" in result.stderr


def test_review_preflight_without_git_repository_succeeds(
    bd, tmp_path, monkeypatch
):
    """Der Vorlauf bindet den Bericht nicht mehr an einen Quellstand
    und braucht deshalb kein Git-Repository am cwd."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ki-dev.handoff.preflight]\n"
        "corrections = []\n"
        f"checks = [{_command('ok', 'print(1)')}]\n"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 0
    assert "PRUEFBERICHT vorlauf-start=" in result.stdout
    assert result.stderr == "Vorlauf: ok läuft (Timeout 5 s) …\n"


def test_review_preflight_artifact_failure_without_traceback(
    bd, tmp_path, monkeypatch
):
    """Ein Artefaktfehler ausserhalb eines einzelnen Befehls muss ein
    kurzer Reparaturbefund mit Exit 1 sein, kein unbehandelter
    Traceback."""
    _preflight_project(
        tmp_path, checks=f"[{_command('ok', 'print(1)')}]"
    )
    blocker = tmp_path / ".local" / "handoff" / "preflight"
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("kein Verzeichnis")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    # Ein kontrolliertes _fail() endet als SystemExit ueber typer.Exit;
    # ein unbehandelter OSError waere eine andere Exception-Klasse und
    # keine saubere Reparaturmeldung.
    assert type(result.exception) is SystemExit
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Vorlauf-Ausführungsfehler" in result.stderr


def test_review_without_preflight_config_exits_2(
    bd, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Vorlauf-Konfiguration ungültig" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["step", "x-1", "--step", "build", "--review-of", "build"],
        ["step", "x-1", "--review-of", "map"],
        [
            "step",
            "map",
            "--review-of",
            "build",
            "--agent",
            "codex",
            "--session",
            "s-1",
        ],
        [
            "step",
            "x-1",
            "--step",
            "review",
            "--review-of",
            "unbekannt",
        ],
    ],
)
def test_review_of_wrong_combination_exits_2_without_bd(bd, args):
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert bd.calls == []


@pytest.mark.parametrize("target", ["map", "graph"])
def test_review_of_source_target_needs_only_refs(bd, target):
    bead = {
        k: v
        for k, v in FULL.items()
        if k not in ("design", "acceptance_criteria")
    }
    bd.state["stdout"] = json.dumps([bead])
    result = runner.invoke(
        app,
        ["step", "x-1", "--step", "review", "--review-of", target],
    )
    assert result.exit_code == 0
    assert result.stdout.startswith("Schritt: review\n")
    assert f"Reviewziel: {target}\n" in result.stdout
    assert "PRUEFBERICHT" not in result.stdout


@pytest.mark.parametrize("target", ["map", "graph", "materialize"])
def test_review_of_source_target_runs_no_preflight_or_process(
    bd, tmp_path, monkeypatch, target
):
    """Quellen-/Materialisierungsreviews laufen ohne pyproject.toml
    und ohne Prozessaufrufe (AC4: kein Code-Pruefvorlauf)."""
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["step", "x-1", "--step", "review", "--review-of", target],
    )
    assert result.exit_code == 0
    assert "PRUEFBERICHT" not in result.stdout
    preflight_dir = tmp_path / ".local" / "handoff" / "preflight"
    assert not preflight_dir.exists()


@pytest.mark.parametrize("target", ["map", "graph", "materialize"])
def test_review_of_source_target_ignores_failing_preflight(
    bd, tmp_path, monkeypatch, target
):
    """AC4: Nur build fuehrt den Code-Pruefvorlauf aus. Ein konfigu-
    rierter, hier absichtlich fehlschlagender Check darf ein Quellen-/
    Materialisierungsreview nicht beeinflussen: Es startet ihn gar
    nicht erst."""
    fail_code = "import sys; sys.exit(1)"
    _preflight_project(
        tmp_path, checks=f"[{_command('fails', fail_code)}]"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["step", "x-1", "--step", "review", "--review-of", target],
    )
    assert result.exit_code == 0
    assert "PRUEFBERICHT" not in result.stdout
    preflight_dir = tmp_path / ".local" / "handoff" / "preflight"
    assert not preflight_dir.exists()


def test_review_of_materialize_needs_refs_and_contract(bd):
    bead = {k: v for k, v in FULL.items() if k != "metadata"}
    bd.state["stdout"] = json.dumps([bead])
    result = runner.invoke(
        app,
        [
            "step",
            "x-1",
            "--step",
            "review",
            "--review-of",
            "materialize",
        ],
    )
    assert result.exit_code == 2
    assert "metadata.handoff.source_refs" in result.stderr


def test_review_of_build_matches_plain_review(
    bd, tmp_path, monkeypatch
):
    _preflight_project(
        tmp_path, checks=f"[{_command('ok', 'print(1)')}]"
    )
    monkeypatch.chdir(tmp_path)
    # Feste Zeit: der Bericht trägt vorlauf-start, zwei Läufe könnten
    # sonst an einer Sekundengrenze verschieden sein.
    monkeypatch.setattr(
        handoff_preflight,
        "_utc_now",
        lambda: datetime(2026, 10, 3, 12, 0, tzinfo=UTC),
    )
    plain = runner.invoke(app, ["step", "x-1", "--step", "review"])
    explicit = runner.invoke(
        app,
        ["step", "x-1", "--step", "review", "--review-of", "build"],
    )
    assert plain.exit_code == explicit.exit_code == 0
    assert plain.stdout == explicit.stdout


def test_review_validates_bead_before_preflight_config(
    bd, tmp_path, monkeypatch
):
    """Kein pyproject.toml am cwd noetig, wenn der Bead bereits formal
    unvollstaendig ist: Bead-Validierung geht der Konfiguration vor."""
    bd.state["stdout"] = json.dumps(
        [{k: v for k, v in FULL.items() if k != "design"}]
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 2
    assert "design" in result.stderr
    assert "Vorlauf-Konfiguration" not in result.stderr


# ---------------------------------------------------------------------
# --preflight-args und Reparaturbefund (zip.6)
# ---------------------------------------------------------------------

_NEEDS_SKIP = (
    "import sys; sys.exit(0 if sys.argv[1:] == ['--skip'] else 1)"
)


def _preflight_artifacts(tmp_path: Path) -> list[Path]:
    directory = tmp_path / ".local" / "handoff" / "preflight"
    return list(directory.glob("*"))


def test_review_preflight_args_are_appended_and_marked(
    bd, tmp_path, monkeypatch
):
    _preflight_project(
        tmp_path, checks=f"[{_command('tests', _NEEDS_SKIP)}]"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        [
            "step", "x-1", "--step", "review",
            "--preflight-args", "tests=--skip",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert "- tests: PASS" in result.stdout
    assert "[ergänzt per --preflight-args]" in result.stdout


def test_review_without_preflight_args_still_fails_the_same_check(
    bd, tmp_path, monkeypatch
):
    _preflight_project(
        tmp_path, checks=f"[{_command('tests', _NEEDS_SKIP)}]"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 1


@pytest.mark.parametrize(
    "value", ["tset=--skip", "tests", "tests=", "tests=-k 'offen"]
)
def test_review_invalid_preflight_args_exit_2_before_any_write(
    bd, tmp_path, monkeypatch, value
):
    _preflight_project(
        tmp_path, checks=f"[{_command('tests', 'pass')}]"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["step", "x-1", "--step", "review", "--preflight-args", value],
    )
    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr.startswith("Aufruf ungültig: --preflight-args")
    assert "Vorlauf:" not in result.stderr
    assert _preflight_artifacts(tmp_path) == []


@pytest.mark.parametrize(
    "extra",
    [
        ["--step", "build"],
        ["--step", "review", "--review-of", "map"],
        ["--step", "review", "--review-of", "materialize"],
    ],
)
def test_preflight_args_outside_build_review_is_call_error(
    bd, tmp_path, monkeypatch, extra
):
    _preflight_project(
        tmp_path, checks=f"[{_command('tests', 'pass')}]"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["step", "x-1", *extra, "--preflight-args", "tests=-x"]
    )
    assert result.exit_code == 2
    assert "gelten nur für den Vorlauf" in result.stderr
    assert bd.calls == []
    assert _preflight_artifacts(tmp_path) == []


def test_preflight_args_with_map_form_is_call_error(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        [
            "step", "map", "--agent", "codex", "--session", "s",
            "--preflight-args", "tests=-x",
        ],
    )
    assert result.exit_code == 2
    assert "--preflight-args" in result.stderr


def test_repair_finding_names_config_and_preflight_args_way_out(
    bd, tmp_path, monkeypatch
):
    _preflight_project(
        tmp_path,
        checks=(
            f"[{_command('ok', 'pass')}, "
            f"{_command('tests', 'import sys; sys.exit(1)')}]"
        ),
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 1
    assert (
        "Konfiguration: pyproject.toml [tool.ki-dev.handoff.preflight]"
        in result.stderr
    )
    hint = "Einmalig ergänzen: --preflight-args tests=ARGS"
    assert hint in result.stderr


def test_repair_finding_after_correction_failure_has_no_hint(
    bd, tmp_path, monkeypatch
):
    """Eine fehlgeschlagene Korrektur lässt sich nicht per
    --preflight-args umgehen; der Befund nennt nur die Konfiguration."""
    _preflight_project(
        tmp_path,
        corrections=f"[{_command('fmt', 'import sys; sys.exit(3)')}]",
        checks=f"[{_command('tests', 'pass')}]",
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 1
    assert "Konfiguration: pyproject.toml" in result.stderr
    assert "Einmalig ergänzen" not in result.stderr


def test_former_check_args_option_is_gone(bd, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["step", "x-1", "--step", "review", "--check-args", "tests=-x"],
    )
    assert result.exit_code == 2
    assert bd.calls == []


def test_review_preflight_skip_is_a_partial_run_without_pass(
    bd, tmp_path, monkeypatch
):
    marker = tmp_path / "lint-gestartet"
    lint = _command("lint", f"open({str(marker)!r}, 'w').close()")
    _preflight_project(
        tmp_path, checks=f"[{_command('tests', 'pass')}, {lint}]"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        [
            "step", "x-1", "--step", "review",
            "--preflight-skip", "lint=nur Doku geändert",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert not marker.exists()
    assert "- tests: PASS" in result.stdout
    skipped = "- lint: SKIPPED ausgelassen per --preflight-skip: nur"
    assert skipped in result.stdout
    assert "TEILLAUF:" in result.stdout
    assert "ist PASS ausgeschlossen" in result.stdout


def test_full_review_run_keeps_pass_without_partial_note(
    bd, tmp_path, monkeypatch
):
    _preflight_project(
        tmp_path, checks=f"[{_command('tests', 'pass')}]"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 0, result.stderr
    assert "TEILLAUF:" not in result.stdout
    assert "PASS | CHANGES | NEEDS_DECISION" in result.stdout


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (["--preflight-skip", "fmt=x"], "keine konfigurierte Prüfung"),
        (["--preflight-skip", "lint="], "einzeilig, nichtleer"),
        (
            [
                "--preflight-args", "tests=-x",
                "--preflight-skip", "tests=x",
            ],
            "zugleich",
        ),
    ],
)
def test_invalid_preflight_skip_exit_2_before_any_command(
    bd, tmp_path, monkeypatch, options, message
):
    _preflight_project(
        tmp_path,
        corrections=f"[{_command('fmt', 'pass')}]",
        checks=(
            f"[{_command('tests', 'pass')}, "
            f"{_command('lint', 'pass')}]"
        ),
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["step", "x-1", "--step", "review", *options]
    )
    assert result.exit_code == 2
    assert message in result.stderr
    assert "Vorlauf:" not in result.stderr
    assert _preflight_artifacts(tmp_path) == []


# ---------------------------------------------------------------------
# Mitgelieferte Leitlinien (zip.1)
# ---------------------------------------------------------------------

_OK_CHECK = f"[{_command('ok', 'print(1)')}]"


def test_productive_step_appends_selected_guidelines(
    bd, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["step", "x-1", "--step", "materialize"]
    )
    assert result.exit_code == 0, result.stderr
    base, block = result.stdout.split("\nLEITLINIEN (mitgeliefert", 1)
    assert "Hinweis für den Menschen" in base
    for prefix in ("Q0", "Q1"):
        assert f"- {prefix}:materialize-task" in block
        assert f"- {prefix}:shared" in block
        assert block.count(f"- {prefix}:shared") == 1
        assert f"{prefix}:materialize-review" not in block
        assert f"{prefix}:build-task" not in block
    assert (
        "--- docs/policies/technikleitlinie.de.yaml#common ---\n"
        "## Q1 common\n\n- Q1:common\n"
    ) in block


def test_source_review_appends_review_guidelines(
    bd, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        ["step", "x-1", "--step", "review", "--review-of", "graph"],
    )
    assert result.exit_code == 0, result.stderr
    assert "- Q0:graph-task" in result.stdout
    assert "- Q0:graph-review" in result.stdout
    assert ".local" not in {p.name for p in tmp_path.iterdir()}


def test_build_review_appends_guidelines_after_report(
    bd, tmp_path, monkeypatch
):
    _preflight_project(tmp_path, checks=_OK_CHECK)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 0, result.stderr
    text = result.stdout
    assert text.index("PRUEFBERICHT") < text.index("LEITLINIEN")
    assert "- Q0:build-review" in text
    assert "- Q1:build-task" in text


def test_missing_guideline_source_blocks_preflight(
    bd, tmp_path, monkeypatch
):
    _preflight_project(tmp_path, checks=_OK_CHECK)
    (tmp_path / "docs/policies/technikleitlinie.de.yaml").unlink()
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == (
        "Leitlinienquelle nicht lesbar: docs/policies/"
        "technikleitlinie.de.yaml: nicht lesbar (FileNotFoundError)\n"
    )
    assert not (tmp_path / ".local").exists()


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ("GEHEIM: [\n", "ungültiges YAML (Zeile 2, Spalte 1)"),
        ('{"title": "GEHEIM"}', "(Wurzel): Pflichtfeld"),
    ],
)
def test_invalid_guideline_source_exits_2_without_raw_text(
    bd, tmp_path, monkeypatch, content, problem
):
    _preflight_project(tmp_path, checks=_OK_CHECK)
    source = tmp_path / "docs/policies/programmierleitlinie.de.yaml"
    source.write_text(content)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr.startswith(
        "Leitlinienquelle ungültig: "
        "docs/policies/programmierleitlinie.de.yaml\n"
    )
    assert problem in result.stderr
    assert "GEHEIM" not in result.stderr
    assert not (tmp_path / ".local").exists()
