"""CLI-Tests für ``ki-dev step --step review --next-turn``.

Alle Läufe mit Vorlauf (Ziel build) arbeiten in temporären Projekten;
im Repo selbst liefe der Vorlauf rekursiv pytest.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ki_dev.cli import app
from tests.fake_bd_command import BdScript
from tests.guideline_fixtures import write_guidelines
from tests.test_handoff_cli import FULL, _command, _preflight_project

runner = CliRunner()

BASE = ["step", "x-1", "--step", "review", "--next-turn"]
FAIL = "import sys; sys.exit(1)"
READONLY_SHOW = ["bd", "--readonly", "show"]


@pytest.fixture
def bd(monkeypatch, tmp_path_factory):
    fake = BdScript(
        tmp_path_factory.mktemp("bd"),
        stdout=json.dumps([FULL]),
        stderr="boese\n" * 30,
    )
    fake.install(monkeypatch)
    return fake


def assert_follow_up_message(text: str) -> None:
    """Kurze Folgenachricht in die bisherige Review-Sitzung: keine
    zweite Rollenübergabe, die der Erneut-Prüfung widerspräche."""
    assert "bisherige, vom Schreibagenten getrennte Sitzung" in text
    assert "frischer" not in text
    assert "früheren Reviews" not in text
    assert "Rolle:" not in text
    assert text.count("Hinweis für den Menschen:") == 1
    assert (
        text.rstrip()
        .splitlines()[-1]
        .startswith("Hinweis für den Menschen:")
    )


def _project(tmp_path: Path, monkeypatch, *, check=None, limit=None):
    """Projekt mit einer Prüfung ``tests`` (Standard: besteht)."""
    check = check or _command("tests", "print(1)")
    _preflight_project(tmp_path, checks=f"[{check}]")
    if limit is not None:
        _set_limit(tmp_path, limit)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _set_limit(project: Path, value: str) -> None:
    path = project / "pyproject.toml"
    path.write_text(
        f"[tool.ki-dev.handoff]\nfeedback_max_chars = {value}\n"
        + path.read_text()
    )


def _artifacts(project: Path) -> list[Path]:
    return list((project / ".local" / "handoff").glob("**/*.json"))


def _feedback(tmp_path: Path, text: str | bytes) -> str:
    path = tmp_path / "rueckmeldung.txt"
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_bytes(text.encode("utf-8"))
    return str(path)


# ---------------------------------------------------------------------
# Empfänger, Exitcode, Bericht
# ---------------------------------------------------------------------


def test_passing_check_routes_to_reviewer_with_report(
    bd, tmp_path, monkeypatch
):
    _project(tmp_path, monkeypatch)
    result = runner.invoke(app, BASE)
    assert result.exit_code == 0
    assert result.stdout.startswith("Empfänger: Review-Agent")
    assert "\nReviewziel: build\nBead: x-1 - " in result.stdout
    assert_follow_up_message(result.stdout)
    assert "PRUEFBERICHT vorlauf-start=" in result.stdout
    assert "- tests: PASS" in result.stdout
    assert "Erneute Prüfung nach Korrekturen:" in result.stdout
    assert "Grüne Tests sind kein Review-PASS" in result.stdout
    assert "PASS | CHANGES | NEEDS_DECISION" in result.stdout
    assert "Rückmeldung des Schreibagenten" not in result.stdout
    assert result.stderr == "Vorlauf: tests läuft (Timeout 5 s) …\n"
    assert "GEHEIME" not in result.stdout
    assert bd.calls == [["bd", "--readonly", "show", "x-1", "--json"]]


def test_failing_check_routes_to_builder_on_stdout(
    bd, tmp_path, monkeypatch
):
    failing = _command("tests", FAIL)
    _project(tmp_path, monkeypatch, check=failing, limit="600")
    result = runner.invoke(app, BASE)
    assert result.exit_code == 1
    assert result.stdout.startswith("Empfänger: Bau-Agent")
    assert "Bead: x-1 - Titel [red]rot[/red]\n" in result.stdout
    assert (
        "Bitte die gemeldeten Fehler beheben. Melde anschließend nur "
        "zurück, was aus Diff und Prüfergebnissen nicht hervorgeht, "
        "etwa offene Entscheidungen oder Hindernisse."
    ) in result.stdout
    assert "höchstens 600 Zeichen" in result.stdout
    assert "- tests: FAIL" in result.stdout
    artifact_line = "Vollständig: .local/handoff/preflight/"
    assert result.stdout.count(artifact_line) == 1
    assert "PRUEFBERICHT" not in result.stdout
    # stderr trägt nur den Fortschritt, der Befund steht nicht doppelt.
    assert result.stderr == "Vorlauf: tests läuft (Timeout 5 s) …\n"


def test_correction_failure_routes_to_builder_with_omitted_checks(
    bd, tmp_path, monkeypatch
):
    _preflight_project(
        tmp_path,
        corrections=f"[{_command('fmt', 'import sys; sys.exit(3)')}]",
        checks=f"[{_command('tests', 'print(1)')}]",
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, BASE)
    assert result.exit_code == 1
    assert result.stdout.startswith("Empfänger: Bau-Agent")
    assert "- fmt: FAIL" in result.stdout
    assert "- tests: OMITTED" in result.stdout


def test_start_failure_routes_to_builder(bd, tmp_path, monkeypatch):
    missing = (
        '{name = "tests", argv = ["gibt-es-nicht-xyz"], timeout_s = 5}'
    )
    _project(tmp_path, monkeypatch, check=missing)
    result = runner.invoke(app, BASE)
    assert result.exit_code == 1
    assert result.stdout.startswith("Empfänger: Bau-Agent")
    assert "- tests: FAIL" in result.stdout


def test_timeout_routes_to_builder(bd, tmp_path, monkeypatch):
    slow = _command("tests", "import time; time.sleep(30)", 0.2)
    _project(tmp_path, monkeypatch, check=slow)
    result = runner.invoke(app, BASE)
    assert result.exit_code == 1
    assert result.stdout.startswith("Empfänger: Bau-Agent")
    assert "- tests: FAIL" in result.stdout


def test_artifact_failure_routes_to_builder_without_artifact_line(
    bd, tmp_path, monkeypatch
):
    _project(tmp_path, monkeypatch)
    blocker = tmp_path / ".local" / "handoff" / "preflight"
    blocker.parent.mkdir(parents=True)
    blocker.write_text("kein Verzeichnis")
    result = runner.invoke(app, BASE)
    assert type(result.exception) is SystemExit
    assert result.exit_code == 1
    assert result.stdout.startswith("Empfänger: Bau-Agent")
    assert "Vorlauf-Ausführungsfehler" in result.stdout
    assert "- tests: PASS" in result.stdout
    assert "Vollständig:" not in result.stdout


def test_check_args_still_apply_with_next_turn(
    bd, tmp_path, monkeypatch
):
    needs_skip = _command(
        "tests",
        "import sys; sys.exit(0 if sys.argv[1:] == ['--skip'] else 1)",
    )
    _project(tmp_path, monkeypatch, check=needs_skip)
    result = runner.invoke(app, [*BASE, "--check-args", "tests=--skip"])
    assert result.exit_code == 0, result.stderr
    assert "[ergänzt per --check-args]" in result.stdout


@pytest.mark.parametrize("target", ["map", "graph", "materialize"])
def test_source_targets_rereview_without_preflight(
    bd, tmp_path, monkeypatch, target
):
    monkeypatch.chdir(tmp_path)  # weder pyproject.toml noch Vorlauf
    result = runner.invoke(app, [*BASE, "--review-of", target])
    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("Empfänger: Review-Agent")
    assert f"Reviewziel: {target}\n" in result.stdout
    assert_follow_up_message(result.stdout)
    assert "Erneute Prüfung nach Korrekturen:" in result.stdout
    assert "PRUEFBERICHT" not in result.stdout
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "toml",
    [
        "kaputt = [",
        "[tool.ki-dev.handoff]\nfeedback_max_chars = 0\n",
        "[tool.ki-dev]\nhandoff = 7\n",
    ],
)
@pytest.mark.parametrize("target", ["map", "graph", "materialize"])
def test_source_target_rejects_invalid_config_without_feedback(
    bd, tmp_path, monkeypatch, target, toml
):
    (tmp_path / "pyproject.toml").write_text(toml)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, [*BASE, "--review-of", target])
    assert result.exit_code == 2, result.stdout
    assert result.stdout == ""
    assert "Konfiguration ungültig" in result.stderr


def test_source_target_needs_no_preflight_table(
    bd, tmp_path, monkeypatch
):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.ki-dev.handoff]\nfeedback_max_chars = 50\n"
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, [*BASE, "--review-of", "map"])
    assert result.exit_code == 0, result.stderr
    assert result.stderr == ""
    assert _artifacts(tmp_path) == []


def test_explicit_review_of_build_matches_default(
    bd, tmp_path, monkeypatch
):
    _project(tmp_path, monkeypatch)
    plain = runner.invoke(app, BASE)
    explicit = runner.invoke(app, [*BASE, "--review-of", "build"])
    assert plain.exit_code == explicit.exit_code == 0
    first_line = plain.stdout.splitlines()[0]
    assert first_line == explicit.stdout.splitlines()[0]
    assert "Reviewziel: build" in explicit.stdout


def test_without_next_turn_failure_keeps_empty_stdout(
    bd, tmp_path, monkeypatch
):
    _project(tmp_path, monkeypatch, check=_command("tests", FAIL))
    write_guidelines(tmp_path)
    result = runner.invoke(app, ["step", "x-1", "--step", "review"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Vorlauf ohne Review-Übergabe" in result.stderr


# ---------------------------------------------------------------------
# Aufrufmatrix
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["step", "x-1", "--step", "build", "--next-turn"],
        ["step", "x-1", "--step", "map", "--next-turn"],
        ["step", "x-1", "--step", "review", "--feedback-file", "f"],
        ["step", "x-1", "--step", "build", "--feedback-file", "f"],
        [
            "step",
            "map",
            "--agent",
            "codex",
            "--session",
            "s",
            "--next-turn",
        ],
        [
            "step",
            "map",
            "--agent",
            "codex",
            "--session",
            "s",
            "--feedback-file",
            "f",
        ],
        ["step", "--next-turn", "--feedback-file", "f"],
    ],
)
def test_wrong_option_combination_exits_2_without_bd(bd, args):
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert bd.calls == []


# ---------------------------------------------------------------------
# Rückmeldung: Quelle, Grenzen, Kennzeichnung
# ---------------------------------------------------------------------


def test_feedback_is_attached_marked_and_quoted_for_reviewer(
    bd, tmp_path, monkeypatch
):
    _project(tmp_path, monkeypatch)
    path = _feedback(tmp_path, "Zeile eins\n\x1b[31mrot\x1b[0m\x00zwei")
    result = runner.invoke(app, [*BASE, "--feedback-file", path])
    assert result.exit_code == 0, result.stderr
    assert "unbestätigte Aussage" in result.stdout
    assert "\n| Zeile eins\n| [31mrot[0mzwei\n" in result.stdout
    assert "\x1b" not in result.stdout
    assert "\x00" not in result.stdout


def test_feedback_is_attached_to_builder_message(
    bd, tmp_path, monkeypatch
):
    _project(tmp_path, monkeypatch, check=_command("tests", FAIL))
    path = _feedback(tmp_path, "offene Frage")
    result = runner.invoke(app, [*BASE, "--feedback-file", path])
    assert result.exit_code == 1
    assert "unbestätigte Aussage" in result.stdout
    assert "| offene Frage" in result.stdout


def test_feedback_from_stdin_equals_file(bd, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    text = "Ünïcode ✓\r\nzweite Zeile"
    path = _feedback(tmp_path, text)
    args = [*BASE, "--review-of", "map"]
    from_file = runner.invoke(app, [*args, "--feedback-file", path])
    from_stdin = runner.invoke(
        app, [*args, "--feedback-file", "-"], input=text.encode()
    )
    assert from_file.exit_code == from_stdin.exit_code == 0
    assert from_file.stdout == from_stdin.stdout
    assert "| Ünïcode ✓\n| zweite Zeile\n" in from_file.stdout + "\n"


def test_without_feedback_option_stdin_is_not_read(
    bd, tmp_path, monkeypatch
):
    def tripwire():
        raise AssertionError("stdin wurde angefordert")

    monkeypatch.setattr("ki_dev.handoff_cli._stdin_binary", tripwire)
    monkeypatch.chdir(tmp_path)
    write_guidelines(tmp_path)
    for args in (
        [*BASE, "--review-of", "map"],
        ["step", "x-1", "--step", "build"],
    ):
        result = runner.invoke(app, args, input=b"unbeachtet")
        assert result.exit_code == 0, result.exception


def test_default_limit_is_600_characters(bd, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # keine pyproject.toml: Standard
    args = [*BASE, "--review-of", "map", "--feedback-file", "-"]
    ok = runner.invoke(app, args, input=("ä" * 600).encode())
    over = runner.invoke(app, args, input=("ä" * 601).encode())
    assert ok.exit_code == 0
    assert over.exit_code == 2
    assert over.stdout == ""
    assert "600 Zeichen" in over.stderr


def test_configured_limit_counts_characters_not_bytes(
    bd, tmp_path, monkeypatch
):
    _project(tmp_path, monkeypatch, limit="3")
    for text, code in (
        ("äö😀", 0),  # 3 Zeichen, 8 Byte
        ("a b\n", 2),  # 4 Zeichen inkl. Leerraum und Zeilenumbruch
        ("😀😀😀😀", 2),
        ("a\r\n", 0),  # CRLF zählt als zwei Zeichen
        ("a\r\nb", 2),
    ):
        result = runner.invoke(
            app, [*BASE, "--feedback-file", _feedback(tmp_path, text)]
        )
        assert result.exit_code == code, (text, result.stderr)
    assert "3 Zeichen" in result.stderr


def test_over_limit_is_not_truncated_and_shows_no_text(
    bd, tmp_path, monkeypatch
):
    _project(tmp_path, monkeypatch, limit="5")
    result = runner.invoke(
        app,
        [*BASE, "--feedback-file", _feedback(tmp_path, "GEHEIMTEXT")],
    )
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "GEHEIMTEXT" not in result.stderr
    assert _artifacts(tmp_path) == []


@pytest.mark.parametrize("text", ["", "   ", "\n\t \n"])
def test_empty_feedback_exits_2_before_preflight(
    bd, tmp_path, monkeypatch, text
):
    _project(tmp_path, monkeypatch)
    result = runner.invoke(
        app, [*BASE, "--feedback-file", _feedback(tmp_path, text)]
    )
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "leer" in result.stderr
    assert result.stderr.count("Vorlauf:") == 0
    assert _artifacts(tmp_path) == []


def test_empty_stdin_exits_2(bd, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        [*BASE, "--review-of", "map", "--feedback-file", "-"],
        input=b"",
    )
    assert result.exit_code == 2


def test_unreadable_feedback_exits_1_without_text(
    bd, tmp_path, monkeypatch
):
    marker = tmp_path / "gelaufen"
    code = f"open({str(marker)!r}, 'w').close()"
    _project(tmp_path, monkeypatch, check=_command("tests", code))
    for target in (
        str(tmp_path / "fehlt.txt"),
        str(tmp_path),  # Verzeichnis
        _feedback(tmp_path, b"\xff\xfe GEHEIMBYTES"),
    ):
        result = runner.invoke(app, [*BASE, "--feedback-file", target])
        assert result.exit_code == 1, target
        assert result.stdout == ""
        assert "GEHEIMBYTES" not in result.stderr
        assert "Traceback" not in result.stderr
    assert not marker.exists()
    assert _artifacts(tmp_path) == []


def test_invalid_stdin_bytes_exit_1(bd, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        [*BASE, "--review-of", "map", "--feedback-file", "-"],
        input=b"\xff\xfe",
    )
    assert result.exit_code == 1
    assert "UTF-8" in result.stderr


@pytest.mark.parametrize(
    "value", ["0", "-1", '"600"', "true", "1.5", "600.0", "[1]"]
)
def test_invalid_limit_exits_2_before_preflight(
    bd, tmp_path, monkeypatch, value
):
    _project(tmp_path, monkeypatch, limit=value)
    for args in (
        BASE,
        [*BASE, "--feedback-file", _feedback(tmp_path, "x")],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 2, (value, result.stderr)
        assert result.stdout == ""
        assert "feedback_max_chars" in result.stderr
    assert _artifacts(tmp_path) == []


def test_broken_toml_with_feedback_exits_2(bd, tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text("kaputt = [")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app,
        [
            *BASE,
            "--review-of",
            "map",
            "--feedback-file",
            _feedback(tmp_path, "x"),
        ],
    )
    assert result.exit_code == 2
    assert "TOML" in result.stderr


def test_bead_is_validated_before_feedback_is_read(
    bd, tmp_path, monkeypatch
):
    bd.state["stdout"] = json.dumps(
        [{k: v for k, v in FULL.items() if k != "design"}]
    )
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, [*BASE, "--feedback-file", str(tmp_path / "fehlt.txt")]
    )
    assert result.exit_code == 2
    assert "design" in result.stderr


def test_build_without_preflight_config_exits_2(
    bd, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, BASE)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Vorlauf-Konfiguration" in result.stderr


def test_notes_and_comments_are_never_read_or_written(
    bd, tmp_path, monkeypatch
):
    _project(tmp_path, monkeypatch)
    result = runner.invoke(app, BASE)
    assert "GEHEIM" not in result.stdout + result.stderr
    assert all(call[:3] == READONLY_SHOW for call in bd.calls)
