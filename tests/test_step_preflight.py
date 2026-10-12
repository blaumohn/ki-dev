from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from plumbum import local
from plumbum.machines.local import LocalMachine

from ki_dev.flow import templates
from ki_dev.ops.checks.options import (
    PreflightOptionError,
    apply_preflight_options,
    parse_preflight_args,
    parse_preflight_skip,
)
from ki_dev.ops.checks.preflight import (
    ADDED_MARKER,
    ARTIFACT_DIR,
    CommandResult,
    CommandSpec,
    PreflightConfig,
    PreflightConfigError,
    PreflightExecutionError,
    format_command_result,
    load_preflight_config,
    progress_line,
    run_preflight,
)
from ki_dev.ops.context.bead_input import BeadInput
from tests.turn_helpers import (
    render_review_handoff,
)

PARTIAL_RUN_NOTE = templates.text("turns", "partial-run-note")


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "test")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "README.md").write_text("x\n")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _pyproject(root: Path, table: str) -> None:
    (root / "pyproject.toml").write_text(
        "[tool.ki-dev.handoff.preflight]\n" + table
    )


def _py(name: str, code: str, timeout_s: float = 10.0) -> CommandSpec:
    return CommandSpec(name, (sys.executable, "-c", code), timeout_s)


def _ok_config(name: str = "ok") -> PreflightConfig:
    return PreflightConfig(corrections=(), checks=(_py(name, "pass"),))


# ---------------------------------------------------------------------
# load_preflight_config
# ---------------------------------------------------------------------


def test_missing_pyproject_is_config_error(tmp_path: Path):
    with pytest.raises(PreflightConfigError):
        load_preflight_config(tmp_path)


def test_missing_preflight_table_is_config_error(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[tool.other]\nx = 1\n")
    with pytest.raises(PreflightConfigError):
        load_preflight_config(tmp_path)


def test_missing_checks_is_config_error(tmp_path: Path):
    _pyproject(tmp_path, "corrections = []\n")
    with pytest.raises(PreflightConfigError, match="checks"):
        load_preflight_config(tmp_path)


def test_empty_checks_is_config_error(tmp_path: Path):
    _pyproject(tmp_path, "corrections = []\nchecks = []\n")
    with pytest.raises(PreflightConfigError, match="checks"):
        load_preflight_config(tmp_path)


def test_corrections_may_be_absent_or_empty(tmp_path: Path):
    _pyproject(
        tmp_path,
        'checks = [{name = "c", argv = ["true"], timeout_s = 1.0}]\n',
    )
    config = load_preflight_config(tmp_path)
    assert config.corrections == ()
    assert config.checks == (CommandSpec("c", ("true",), 1.0),)


@pytest.mark.parametrize(
    "entry",
    [
        '{argv = ["true"], timeout_s = 1.0}',  # name fehlt
        '{name = "", argv = ["true"], timeout_s = 1.0}',  # name leer
        '{name = "c", timeout_s = 1.0}',  # argv fehlt
        '{name = "c", argv = [], timeout_s = 1.0}',  # argv leer
        '{name = "c", argv = [""], timeout_s = 1.0}',  # leerer Eintrag
        '{name = "c", argv = ["true"]}',  # timeout_s fehlt
        '{name = "c", argv = ["true"], timeout_s = 0}',  # nicht positiv
        '{name = "c", argv = ["true"], timeout_s = -1.0}',
        # falscher Typ:
        '{name = "c", argv = ["true"], timeout_s = "1"}',
    ],
)
def test_invalid_command_entries_are_config_errors(
    tmp_path: Path, entry: str
):
    _pyproject(tmp_path, f"checks = [{entry}]\n")
    with pytest.raises(PreflightConfigError):
        load_preflight_config(tmp_path)


@pytest.mark.parametrize("value", ["inf", "-inf", "nan", "true"])
def test_non_finite_or_non_numeric_timeout_is_config_error(
    tmp_path: Path, value: str
):
    """timeout_s muss positiv und endlich sein. TOML kennt inf/nan,
    und eine Zahlenregel allein laesst sie durch; der Vertrag braucht
    eine echte Prozessfrist."""
    _pyproject(
        tmp_path,
        'checks = [{name = "c", argv = ["true"], '
        f"timeout_s = {value}}}]\n",
    )
    with pytest.raises(PreflightConfigError, match="timeout_s"):
        load_preflight_config(tmp_path)


def test_duplicate_names_across_corrections_and_checks_is_config_error(
    tmp_path: Path,
):
    entry = '{name = "x", argv = ["true"], timeout_s = 1.0}'
    _pyproject(
        tmp_path,
        f"corrections = [{entry}]\nchecks = [{entry}]\n",
    )
    with pytest.raises(PreflightConfigError, match="name"):
        load_preflight_config(tmp_path)


def test_nul_byte_in_argv_is_rejected_before_any_command_runs(
    tmp_path: Path,
):
    """Ein via TOML \\u0000 codiertes NUL im argv scheitert erst beim
    Prozessstart mit ValueError; die Konfiguration muss das vorher
    ablehnen, damit keine Korrektur vor dem Prüffehler bereits lief."""
    _pyproject(
        tmp_path,
        'corrections = [{name = "c1", argv = ["true"], '
        "timeout_s = 1.0}]\n"
        'checks = [{name = "c2", argv = ["true", "\\u0000"], '
        "timeout_s = 1.0}]\n",
    )
    with pytest.raises(PreflightConfigError, match="NUL"):
        load_preflight_config(tmp_path)


@pytest.mark.parametrize("escape", ["\\r", "\\n"])
def test_cr_or_lf_in_argv_is_rejected_before_any_command_runs(
    tmp_path: Path, escape: str
):
    """CR/LF im argv sind ebenso verboten wie NUL (Vorlaufvertrag P2)
    und scheitern beim Konfigurationsladen, nicht erst beim Rendern
    der Übergabe."""
    _pyproject(
        tmp_path,
        'corrections = [{name = "c1", argv = ["true"], '
        "timeout_s = 1.0}]\n"
        f'checks = [{{name = "c2", argv = ["true", "x{escape}y"], '
        "timeout_s = 1.0}]\n",
    )
    with pytest.raises(PreflightConfigError, match="Zeilenumbruch"):
        load_preflight_config(tmp_path)


def test_invalid_utf8_pyproject_is_config_error(tmp_path: Path):
    """Ungueltige UTF-8-Bytes in pyproject.toml muessen kontrolliert
    abgelehnt werden (Exit 2), nicht als UnicodeDecodeError aus dem
    Konfigurationsladen herausfallen."""
    (tmp_path / "pyproject.toml").write_bytes(
        b"[tool.ki-dev.handoff.preflight]\nchecks = [] # \xff\xfe\n"
    )
    with pytest.raises(PreflightConfigError, match="UTF-8"):
        load_preflight_config(tmp_path)


def test_invalid_toml_is_config_error(tmp_path: Path):
    """Auch syntaktisch kaputtes TOML ist ein Konfigurationsfehler vor
    jeder Schreibwirkung."""
    (tmp_path / "pyproject.toml").write_text("[tool.ki-dev\n")
    with pytest.raises(PreflightConfigError, match="TOML"):
        load_preflight_config(tmp_path)


def test_long_argv_is_accepted_without_length_limit(tmp_path: Path):
    """argv ist nicht in der Länge begrenzt (zip.5 ersetzt die frühere
    100-Zeichen-Grenze); begrenzt wird nur die Anzeige."""
    argv = ["pytest", "--deselect", "tests/" + "x" * 300]
    _pyproject(
        tmp_path, f"checks = [{{name = 'c', argv = {argv!r}, "
        "timeout_s = 1.0}]\n",
    )
    config = load_preflight_config(tmp_path)
    assert config.checks[0].argv == tuple(argv)


# ---------------------------------------------------------------------
# run_preflight: Reihenfolge, Exitcodes, Auslassungen
# ---------------------------------------------------------------------


def test_success_runs_all_and_is_valid(tmp_path: Path):
    repo = _repo(tmp_path)
    config = PreflightConfig(
        corrections=(_py("fmt", "print('fmt ok')"),),
        checks=(_py("tests", "print('tests ok')"),),
    )
    report = run_preflight(config, repo)
    assert report.valid is True
    assert [item.status for item in report.commands] == ["pass", "pass"]
    assert [item.name for item in report.commands] == ["fmt", "tests"]


def test_corrections_run_before_checks(tmp_path: Path):
    repo = _repo(tmp_path)
    order_file = repo / "order.txt"
    config = PreflightConfig(
        corrections=(
            _py(
                "mark",
                "open('order.txt', 'a').write('correction\\n')",
            ),
        ),
        checks=(
            _py(
                "check",
                "open('order.txt', 'a').write('check\\n')",
            ),
        ),
    )
    run_preflight(config, repo)
    assert order_file.read_text().splitlines() == [
        "correction",
        "check",
    ]


def test_first_failing_correction_stops_remaining_and_skips_checks(
    tmp_path: Path,
):
    repo = _repo(tmp_path)
    marker = repo / "checked.txt"
    config = PreflightConfig(
        corrections=(
            _py("first", "import sys; sys.exit(1)"),
            _py("second", "print('sollte nicht laufen')"),
        ),
        checks=(
            _py("would-check", "open('checked.txt','w').write('x')"),
        ),
    )
    report = run_preflight(config, repo)
    assert report.valid is False
    assert not marker.exists()
    statuses = {item.name: item.status for item in report.commands}
    assert statuses["first"] == "fail"
    assert statuses["second"] == "omitted"
    assert statuses["would-check"] == "omitted"


def test_on_start_reports_started_commands_only(tmp_path: Path):
    repo = _repo(tmp_path)
    config = PreflightConfig(
        corrections=(
            _py("first", "import sys; sys.exit(1)"),
            _py("second", "print('ausgelassen')"),
        ),
        checks=(_py("check", "print('ausgelassen')"),),
    )
    lines: list[str] = []
    run_preflight(config, repo, lines.append)
    assert lines == [progress_line(config.corrections[0])]


def test_on_start_precedes_each_command(tmp_path: Path):
    repo = _repo(tmp_path)
    config = PreflightConfig(
        corrections=(_py("fmt", "print(1)"),),
        checks=(_py("tests", "print(2)"),),
    )
    lines: list[str] = []
    run_preflight(config, repo, lines.append)
    assert [line.split()[1] for line in lines] == ["fmt", "tests"]


def test_progress_line_bounds_and_cleans_name():
    spec = CommandSpec("\x1b[31m" + "x" * 5000, ("pruefe",), 360.0)
    line = progress_line(spec)
    assert "\x1b" not in line
    assert len(line) < 300
    assert line.endswith("läuft (Timeout 360 s) …")


def test_checks_all_run_even_if_one_fails(tmp_path: Path):
    repo = _repo(tmp_path)
    config = PreflightConfig(
        corrections=(),
        checks=(
            _py("a", "import sys; sys.exit(1)"),
            _py("b", "print('b lief trotzdem')"),
        ),
    )
    report = run_preflight(config, repo)
    assert report.valid is False
    statuses = {item.name: item.status for item in report.commands}
    assert statuses == {"a": "fail", "b": "pass"}


def test_timeout_is_reported_as_failure(tmp_path: Path):
    repo = _repo(tmp_path)
    config = PreflightConfig(
        corrections=(),
        checks=(
            _py("slow", "import time; time.sleep(2)", timeout_s=0.2),
        ),
    )
    report = run_preflight(config, repo)
    assert report.valid is False
    item = report.commands[0]
    assert item.status == "fail"
    assert item.exit_code is None
    assert "Timeout" in item.bounded_detail


def test_missing_tool_is_reported_as_failure_not_crash(tmp_path: Path):
    repo = _repo(tmp_path)
    config = PreflightConfig(
        corrections=(),
        checks=(
            CommandSpec(
                "ghost", ("ki-dev-tool-das-nicht-existiert",), 5.0
            ),
        ),
    )
    report = run_preflight(config, repo)
    assert report.valid is False
    item = report.commands[0]
    assert item.status == "fail"
    assert item.exit_code is None
    assert "Startfehler" in item.bounded_detail


def test_output_is_bounded_and_control_characters_are_stripped(
    tmp_path: Path,
):
    repo = _repo(tmp_path)
    code = (
        "import sys; "
        "sys.stdout.write('\\x1b[31m' + 'A' * 5000 + '\\x1b[0m'); "
        "sys.exit(1)"
    )
    config = PreflightConfig(corrections=(), checks=(_py("big", code),))
    report = run_preflight(config, repo)
    item = report.commands[0]
    assert item.status == "fail"
    assert "\x1b" not in item.bounded_detail
    assert len(item.bounded_detail) < 1500
    assert "ausgelassen" in item.bounded_detail


def test_argv_is_not_shell_interpreted(tmp_path: Path):
    repo = _repo(tmp_path)
    config = PreflightConfig(
        corrections=(),
        checks=(
            _py("literal", "import sys; sys.stdout.write('$HOME')"),
        ),
    )
    report = run_preflight(config, repo)
    assert report.commands[0].bounded_detail == "$HOME"


def _on_path(
    tmp_path: Path, monkeypatch, name: str, output: str
) -> None:
    """Ein ausfuehrbares Programm anlegen und PATH darauf zeigen
    lassen -- fuer os.environ und fuer Plumbums eigene Kopie, damit
    der Test nicht schon an einem veralteten PATH vorbeilaeuft."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    tool = bindir / name
    tool.write_text(f"#!/bin/sh\nprintf '{output}'\n")
    tool.chmod(0o755)
    path = f"{bindir}{os.pathsep}{os.environ['PATH']}"
    monkeypatch.setenv("PATH", path)


def test_program_name_is_resolved_exactly(
    tmp_path: Path, monkeypatch
):
    """Plumbums which() sucht zu ``pruef_werkzeug`` ersatzweise auch
    ``pruef-werkzeug`` und ``pruef.werkzeug``. Dann liefe ein anderer
    als der konfigurierte Befehl und koennte PASS melden; der Vorlauf
    loest deshalb exakt auf und meldet sonst einen Startfehler."""
    repo = _repo(tmp_path)
    _on_path(tmp_path, monkeypatch, "pruef-werkzeug", "falscher befehl")
    config = PreflightConfig(
        corrections=(),
        checks=(CommandSpec("exakt", ("pruef_werkzeug",), 10.0),),
    )
    # Auch Plumbums eigener PATH zeigt auf das Verzeichnis, sonst
    # scheiterte die Suche schon daran und der Test belegte nicht,
    # dass die Ersatznamen nicht verwendet werden.
    with local.env(PATH=os.environ["PATH"]):
        report = run_preflight(config, repo)
    item = report.commands[0]
    assert item.status == "fail"
    assert "Startfehler" in item.bounded_detail
    assert "falscher befehl" not in item.bounded_detail


def test_program_is_resolved_with_current_path(
    tmp_path: Path, monkeypatch
):
    """Die Programmsuche nutzt den aktuellen PATH, nicht Plumbums beim
    Import gespeicherte Kopie: ein erst zur Laufzeit ergaenztes
    Verzeichnis muss wirken."""
    repo = _repo(tmp_path)
    _on_path(
        tmp_path, monkeypatch, "ki-dev-vorlauf-probe", "werkzeug ok"
    )
    config = PreflightConfig(
        corrections=(),
        checks=(
            CommandSpec("probe", ("ki-dev-vorlauf-probe",), 10.0),
        ),
    )
    report = run_preflight(config, repo)
    item = report.commands[0]
    assert item.status == "pass"
    assert "werkzeug ok" in item.bounded_detail


def test_command_inherits_current_environment(
    tmp_path: Path, monkeypatch
):
    """Der Vorlauf schraenkt die Umgebung nicht ein: Auch eine erst
    zur Laufzeit gesetzte Variable erreicht den Befehl. Plumbum
    uebergibt sonst einen beim Import erstellten Schnappschuss von
    os.environ statt der aktuellen Umgebung des Aufrufers."""
    repo = _repo(tmp_path)
    monkeypatch.setenv("KI_DEV_VORLAUF_PROBE", "gesetzt")
    config = PreflightConfig(
        corrections=(),
        checks=(
            _py(
                "umgebung",
                "import os; "
                "print(os.environ['KI_DEV_VORLAUF_PROBE'])",
            ),
        ),
    )
    report = run_preflight(config, repo)
    assert report.commands[0].status == "pass"
    assert "gesetzt" in report.commands[0].bounded_detail


def test_relative_script_path_runs_from_project_root(
    tmp_path: Path,
):
    """Die Laengengrenze verweist lange Logik in benannte Skripte
    (Vorlaufvertrag P2). Ein relativer Skriptpfad wird deshalb gegen
    die Projektwurzel aufgeloest, nicht gegen das Arbeitsverzeichnis
    des Aufrufers -- sonst waere genau die empfohlene Konfiguration
    ``scripts/pruefe.sh`` je nach Startort ein Startfehler."""
    repo = _repo(tmp_path)
    (repo / "scripts").mkdir()
    script = repo / "scripts" / "pruefe.sh"
    script.write_text("#!/bin/sh\nprintf 'skript ok'\n")
    script.chmod(0o755)
    config = PreflightConfig(
        corrections=(),
        checks=(CommandSpec("skript", ("scripts/pruefe.sh",), 10.0),),
    )
    report = run_preflight(config, repo)
    item = report.commands[0]
    assert item.status == "pass"
    assert "skript ok" in item.bounded_detail


def test_change_during_checks_does_not_invalidate_report(
    tmp_path: Path,
):
    """Der Vorlauf erkennt keine Aenderungen zwischen den Pruefungen:
    Eine Pruefung mit Exitstatus 0 bleibt gueltig, auch wenn sie eine
    Quelldatei veraendert. Bericht und Arbeitsstand ordnet der Mensch
    einander zu."""
    repo = _repo(tmp_path)
    config = PreflightConfig(
        corrections=(),
        checks=(
            _py(
                "mutates",
                "open('README.md', 'a').write('mehr\\n')",
            ),
        ),
    )
    report = run_preflight(config, repo)
    assert report.commands[0].status == "pass"
    assert report.valid is True


def test_runs_without_git_repository(tmp_path: Path):
    """Ohne Fingerprint braucht der Vorlauf kein Git: ein Projekt ohne
    Repository laeuft normal durch, statt an einem Git-Aufruf zu
    scheitern."""
    report = run_preflight(_ok_config(), tmp_path)
    assert report.valid is True


def test_report_names_start_time(tmp_path: Path):
    """Der Bericht nennt statt eines Quellstands nur den Zeitpunkt des
    Vorlaufs (AC2: Bericht mit Zeitpunkt)."""
    before = datetime.now(UTC)
    report = run_preflight(_ok_config(), _repo(tmp_path))
    started = datetime.strptime(
        report.started_at, "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=UTC)
    assert abs((started - before).total_seconds()) < 60


def test_no_commit_or_reset_happens(tmp_path: Path):
    repo = _repo(tmp_path)
    before = _git(repo, "rev-parse", "HEAD")
    config = PreflightConfig(
        corrections=(_py("touch", "open('neu.txt', 'w').write('x')"),),
        checks=(_py("ok", "pass"),),
    )
    run_preflight(config, repo)
    after = _git(repo, "rev-parse", "HEAD")
    assert before == after
    status = _git(repo, "status", "--porcelain")
    assert "neu.txt" in status


def test_writes_local_artifact_with_report(tmp_path: Path):
    repo = _repo(tmp_path)
    config = _ok_config()
    report = run_preflight(config, repo)
    artifacts = list((repo / ARTIFACT_DIR).glob("*.json"))
    assert len(artifacts) == 1
    payload = json.loads(artifacts[0].read_text())
    assert payload["valid"] is True
    assert payload["started_at"] == report.started_at
    assert payload["commands"][0]["name"] == "ok"
    assert payload["commands"][0]["argv"] == list(config.checks[0].argv)


def test_each_run_writes_its_own_artifact(tmp_path: Path):
    """Keine Wiederverwendung alter Resultate: jeder Vorlauf legt ein
    eigenes Artefakt an, auch zwei Laeufe in derselben Sekunde."""
    repo = _repo(tmp_path)
    config = _ok_config()
    run_preflight(config, repo)
    run_preflight(config, repo)
    assert len(list((repo / ARTIFACT_DIR).glob("*.json"))) == 2


def test_artifact_bounds_and_cleans_name(tmp_path: Path):
    """Das gespeicherte Pruefartefakt unterliegt derselben
    Bereinigungs-/Begrenzungspflicht wie die Terminalausgabe: Ein
    ueberlanger name mit ANSI-Codes darf nicht unveraendert im Bericht
    landen (Review-Befund P2)."""
    repo = _repo(tmp_path)
    config = PreflightConfig(
        corrections=(),
        checks=(_py("\x1b[31m" + "x" * 5000, "pass"),),
    )
    run_preflight(config, repo)
    artifacts = list((repo / ARTIFACT_DIR).glob("*.json"))
    payload = json.loads(artifacts[0].read_text())
    name = payload["commands"][0]["name"]
    assert "\x1b" not in name
    assert len(name) < 1000


# ---------------------------------------------------------------------
# Ausführungsfehler außerhalb einzelner Befehle (Review P2)
# ---------------------------------------------------------------------


def test_artifact_write_failure_raises_execution_error(
    tmp_path: Path,
):
    """Belegt den .local/handoff/preflight-Pfad mit einer Datei statt
    einem Verzeichnis, sodass das Schreiben des Prüfartefakts
    fehlschlägt; das darf kein unbehandelter OSError sein."""
    repo = _repo(tmp_path)
    blocker = repo / ARTIFACT_DIR
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("kein Verzeichnis")
    config = _ok_config()
    with pytest.raises(PreflightExecutionError):
        run_preflight(config, repo)


def test_non_utf8_process_output_does_not_crash(tmp_path: Path):
    """Ungültige UTF-8-Bytes in stdout dürfen zu einem gekürzten,
    bereinigten Detail führen, nicht zu einem UnicodeDecodeError.
    Plumbum verwirft die ungültigen Bytes beim Dekodieren; der
    lesbare Rest bleibt erhalten."""
    repo = _repo(tmp_path)
    code = (
        "import sys; "
        "sys.stdout.buffer.write(b'\\xff\\xfe kaputt'); sys.exit(1)"
    )
    config = PreflightConfig(corrections=(), checks=(_py("bad", code),))
    report = run_preflight(config, repo)
    item = report.commands[0]
    assert item.status == "fail"
    assert "kaputt" in item.bounded_detail


def test_execution_error_keeps_passed_correction_and_failed_check(
    tmp_path: Path,
):
    """Korrektur PASS + Check FAIL + Artefaktfehler muss alle Befunde
    erhalten (AC2): Die bestandene Korrektur hat den Arbeitsbaum
    bereits veraendert und wird nicht zurueckgesetzt, der Check-Befund
    ist der Reparaturhinweis -- beides darf nicht mit dem
    Artefaktfehler verlorengehen."""
    repo = _repo(tmp_path)
    blocker = repo / ARTIFACT_DIR
    blocker.parent.mkdir(parents=True, exist_ok=True)
    blocker.write_text("kein Verzeichnis")
    config = PreflightConfig(
        corrections=(_py("touched", "open('x.txt','w').write('x')"),),
        checks=(_py("kaputt", "import sys; sys.exit(1)"),),
    )
    with pytest.raises(PreflightExecutionError) as excinfo:
        run_preflight(config, repo)
    statuses = {
        item.name: item.status for item in excinfo.value.partial_results
    }
    assert statuses == {"touched": "pass", "kaputt": "fail"}
    assert (repo / "x.txt").exists()


def test_format_command_result_bounds_and_cleans_name():
    """name kommt aus der Konfiguration, nicht aus Prozessausgabe,
    unterliegt im Bericht aber derselben Bereinigungs-/Begrenzungs-
    pflicht wie bounded_detail (Review-Befund AC3)."""
    item = CommandResult(
        "\x1b[31m" + "x" * 5000,
        ("true",),
        "pass",
        0,
        "",
        omitted=False,
    )
    line = format_command_result(item)
    assert "\x1b" not in line
    assert len(line) < 1000


def test_format_command_result_keeps_argv_verbatim():
    """Aus argv darf nichts still entfernt werden: Der Mensch soll den
    Befehl woertlich nachvollziehen und erneut starten koennen. CR/LF/
    NUL und Ueberlaenge sind dafuer bereits beim Konfigurationsladen
    ausgeschlossen, statt sie spaeter stumm wegzuputzen."""
    argv = ("pruefe", "--muster=\x1b[31m")
    item = CommandResult("x", argv, "pass", 0, "", omitted=False)
    assert f"[argv={shlex.join(argv)}]" in format_command_result(item)


def test_format_command_result_shows_short_argv_completely():
    """Kurze argv erscheinen vollständig, ohne Interpreterlisten,
    Optionsparser oder Maskierung."""
    argv = ("python", "-c", "print('geheimes skript')")
    item = CommandResult("x", argv, "pass", 0, "", omitted=False)
    line = format_command_result(item)
    assert f"[argv={shlex.join(argv)}]" in line


def test_format_command_result_quotes_argv_unambiguously():
    """ " ".join(argv) macht ["a b"] und ["a", "b"] ununterscheidbar;
    shlex-Quoting muss beide Faelle auseinanderhalten."""
    one_arg = CommandResult("x", ("a b",), "pass", 0, "", omitted=False)
    two_args = CommandResult(
        "x", ("a", "b"), "pass", 0, "", omitted=False
    )
    assert format_command_result(one_arg) != format_command_result(
        two_args
    )


# ---------------------------------------------------------------------
# render_review_handoff: reines Rendering
# ---------------------------------------------------------------------


def _issue() -> BeadInput:
    return BeadInput(
        id="x-1",
        title="Titel",
        description="Beschreibung",
        design="Design",
        acceptance_criteria="AC",
        source_refs=["a.md#L1"],
    )


def test_render_review_handoff_appends_compact_report(tmp_path: Path):
    repo = _repo(tmp_path)
    config = _ok_config()
    report = run_preflight(config, repo)
    text = render_review_handoff(_issue(), report)
    assert text.startswith("Schritt: review\n")
    assert f"PRUEFBERICHT vorlauf-start={report.started_at}" in text
    assert "- ok: PASS" in text
    assert "[argv=" in text


def test_render_review_handoff_names_the_stand_check(
    tmp_path: Path,
):
    """Der Hinweis nennt, dass PASS nur bei unverändertem Stand gilt
    und ki-dev das prüft (ki-dev-ablauf-nyk)."""
    report = run_preflight(_ok_config(), _repo(tmp_path))
    text = render_review_handoff(_issue(), report)
    assert "PASS gilt nur, wenn Arbeitsbaum und Bead" in text
    assert "startet sonst den Vorlauf erneut" in text


def test_format_command_result_includes_argv_and_detail():
    item = CommandResult(
        "fmt",
        ("ruff", "format"),
        "fail",
        1,
        "exit=1\nboom",
        omitted=False,
    )
    line = format_command_result(item)
    assert line.startswith("- fmt: FAIL")
    assert "exit=1" in line
    assert "[argv=ruff format]" in line


def test_format_command_result_marks_omitted_without_exit_code():
    item = CommandResult(
        "b",
        ("true",),
        "omitted",
        None,
        "ausgelassen: vorherige Korrektur fehlgeschlagen",
        omitted=True,
    )
    line = format_command_result(item)
    assert line == (
        "- b: OMITTED ausgelassen: vorherige Korrektur fehlgeschlagen "
        "[argv=true]"
    )


def test_render_review_handoff_does_not_touch_filesystem(
    tmp_path: Path, monkeypatch
):
    report = run_preflight(
        _ok_config(),
        _repo(tmp_path),
    )

    def _forbidden(*args, **kwargs):
        raise AssertionError("render_review_handoff darf nicht I/O tun")

    # Plumbums Prozesseinstieg, nicht subprocess.run: Der Vorlauf
    # startet Befehle ueber Plumbum, eine Sperre auf subprocess.run
    # waere hier wirkungslos.
    monkeypatch.setattr(LocalMachine, "_popen", _forbidden)
    render_review_handoff(_issue(), report)


def test_format_command_result_shortens_long_argv_visibly_on_one_line():
    """Lange argv werden einzeilig gekürzt; Anfang, Ende und die Zahl
    ausgelassener Zeichen bleiben sichtbar (nichts still entfernt)."""
    argv = ("pytest", "--deselect", "tests/" + "x" * 200 + "::t_ende")
    item = CommandResult("t", argv, "pass", 0, "", omitted=False)
    line = format_command_result(item)
    full = shlex.join(argv)
    assert full not in line
    assert "\n" not in line
    assert "[argv=pytest --deselect" in line
    assert "::t_ende]" in line
    assert f"…(+{len(full) - 100})…" in line


def test_artifact_keeps_long_argv_completely(tmp_path: Path):
    repo = _repo(tmp_path)
    argv = (sys.executable, "-c", "pass", "y" * 300)
    config = PreflightConfig(
        corrections=(), checks=(CommandSpec("lang", argv, 10.0),)
    )
    report = run_preflight(config, repo)
    payload = json.loads((repo / report.artifact).read_text())
    assert payload["commands"][0]["argv"] == list(argv)


def test_report_artifact_is_relative_file_under_artifact_dir(
    tmp_path: Path,
):
    repo = _repo(tmp_path)
    report = run_preflight(_ok_config(), repo)
    assert not report.artifact.is_absolute()
    assert report.artifact.parent == ARTIFACT_DIR
    assert (repo / report.artifact).is_file()


def test_render_review_handoff_names_artifact_exactly_once(
    tmp_path: Path,
):
    """Ein gemeinsamer Verweis statt einer Fundstelle je Kürzung."""
    repo = _repo(tmp_path)
    long_argv = (sys.executable, "-c", "pass", "y" * 300)
    config = PreflightConfig(
        corrections=(),
        checks=(
            CommandSpec("a", long_argv, 10.0),
            CommandSpec("b", long_argv, 10.0),
        ),
    )
    report = run_preflight(config, repo)
    text = render_review_handoff(_issue(), report)
    assert text.count("Vollständig:") == 1
    assert f"Vollständig: {report.artifact}\n" in text



# ---------------------------------------------------------------------
# --preflight-args/--preflight-skip: preflight_options
# ---------------------------------------------------------------------


def test_parse_preflight_args_splits_like_a_shell():
    parsed = parse_preflight_args(
        ['tests=-k "not langsam" --deselect a.py::t', "lint=--fix"]
    )
    assert parsed == {
        "tests": ("-k", "not langsam", "--deselect", "a.py::t"),
        "lint": ("--fix",),
    }


def test_parse_preflight_args_has_no_length_limit():
    parsed = parse_preflight_args(["tests=--deselect " + "x" * 500])
    assert parsed["tests"] == ("--deselect", "x" * 500)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("tests", "NAME=ARGS"),
        ("=-k x", "NAME=ARGS"),
        ("  =-k x", "NAME=ARGS"),
        ("tests=", "leer"),
        ("tests=   ", "leer"),
        ("tests=''", "leer"),
        ("tests=-k 'offen", "Quoting"),
        ("tests=-k 'a\nb'", "CR/LF"),
        ("tests=-k a\x00b", "NUL"),
    ],
)
def test_parse_preflight_args_rejects_malformed_values(value, message):
    with pytest.raises(PreflightOptionError, match=message):
        parse_preflight_args([value])


def test_parse_preflight_args_error_does_not_echo_raw_value():
    with pytest.raises(PreflightOptionError) as excinfo:
        parse_preflight_args(["tests=-k 'GEHEIM"])
    assert "GEHEIM" not in str(excinfo.value)


def test_parse_preflight_args_rejects_duplicate_name():
    """Zwei Angaben für dieselbe Prüfung werden nicht still
    zusammengeführt oder überschrieben."""
    with pytest.raises(PreflightOptionError, match="mehrfach"):
        parse_preflight_args(["tests=-x", "tests=-q"])


def _two_checks_config() -> PreflightConfig:
    return PreflightConfig(
        corrections=(_py("fmt", "pass"),),
        checks=(_py("tests", "pass"), _py("lint", "pass")),
    )


def test_apply_preflight_args_appends_to_named_check_only():
    config = apply_preflight_options(
        _two_checks_config(), {"tests": ("-k", "x")}, {}
    )
    tests, lint = config.checks
    assert tests.argv[-2:] == ("-k", "x")
    assert tests.added == ("-k", "x")
    assert lint == _two_checks_config().checks[1]
    assert config.corrections == _two_checks_config().corrections


def test_apply_preflight_args_without_extra_keeps_config():
    assert apply_preflight_options(_two_checks_config(), {}, {}) == (
        _two_checks_config()
    )


@pytest.mark.parametrize("name", ["tset", "fmt"])
def test_apply_preflight_args_rejects_unknown_or_correction_name(name):
    """Ein Tippfehler oder eine Korrektur wird nicht still ignoriert;
    die Meldung nennt die vorhandenen Prüfungen."""
    with pytest.raises(
        PreflightOptionError, match="vorhanden: tests, lint"
    ):
        apply_preflight_options(
            _two_checks_config(), {name: ("-x",)}, {}
        )


def test_added_args_reach_process_artifact_and_report(tmp_path: Path):
    repo = _repo(tmp_path)
    code = (
        "import sys; sys.exit(0 if sys.argv[1:] == ['--skip'] else 1)"
    )
    config = apply_preflight_options(
        PreflightConfig(corrections=(), checks=(_py("tests", code),)),
        {"tests": ("--skip",)},
        {},
    )
    report = run_preflight(config, repo)
    assert report.valid
    payload = json.loads((repo / report.artifact).read_text())
    assert payload["commands"][0]["added_args"] == ["--skip"]
    assert payload["partial"] is True
    assert report.partial
    text = render_review_handoff(_issue(), report)
    assert ADDED_MARKER in text
    assert PARTIAL_RUN_NOTE in text


def test_added_marker_survives_shortened_argv():
    """Auch wenn argv gekürzt ist, bleibt die Ergänzung sichtbar."""
    item = CommandResult(
        "tests",
        ("pytest", "--deselect", "x" * 300),
        "pass",
        0,
        "",
        omitted=False,
        added=("--deselect", "x" * 300),
    )
    line = format_command_result(item)
    assert "…(+" in line
    assert line.endswith(ADDED_MARKER)


def test_unmodified_result_has_no_added_marker():
    item = CommandResult("t", ("true",), "pass", 0, "", omitted=False)
    assert ADDED_MARKER not in format_command_result(item)


# ---------------------------------------------------------------------
# --preflight-skip: begründetes Auslassen, Teillauf ohne PASS
# ---------------------------------------------------------------------


def test_parse_preflight_skip_keeps_reason_per_check():
    parsed = parse_preflight_skip(["lint=nur Doku geändert", "tests=x"])
    assert parsed == {"lint": "nur Doku geändert", "tests": "x"}


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("lint", "NAME=GRUND"),
        ("=nur Doku", "NAME=GRUND"),
        ("lint=", "einzeilig, nichtleer"),
        ("lint=   ", "einzeilig, nichtleer"),
        ("lint=a\nb", "einzeilig, nichtleer"),
        ("lint=" + "x" * 201, "höchstens 200"),
    ],
)
def test_parse_preflight_skip_rejects_malformed_values(value, message):
    with pytest.raises(PreflightOptionError, match=message):
        parse_preflight_skip([value])


def test_parse_preflight_skip_rejects_duplicate_name():
    with pytest.raises(PreflightOptionError, match="mehrfach"):
        parse_preflight_skip(["lint=a", "lint=b"])


@pytest.mark.parametrize("name", ["tset", "fmt"])
def test_skip_rejects_unknown_or_correction_name(name):
    with pytest.raises(PreflightOptionError, match="--preflight-skip"):
        apply_preflight_options(_two_checks_config(), {}, {name: "x"})


def test_same_check_cannot_be_extended_and_skipped():
    with pytest.raises(PreflightOptionError, match="zugleich"):
        apply_preflight_options(
            _two_checks_config(), {"tests": ("-x",)}, {"tests": "x"}
        )


def test_skipped_check_does_not_start_and_is_reported(tmp_path: Path):
    repo = _repo(tmp_path)
    marker = repo / "gestartet"
    code = f"open({str(marker)!r}, 'w').close()"
    config = apply_preflight_options(
        PreflightConfig(
            corrections=(),
            checks=(_py("tests", "pass"), _py("lint", code)),
        ),
        {},
        {"lint": "nur Doku"},
    )
    report = run_preflight(config, repo)
    assert not marker.exists()
    assert report.valid
    assert report.partial
    tests, lint = report.commands
    assert (tests.status, lint.status) == ("pass", "skipped")
    assert lint.skip_reason == "nur Doku"
    assert "ausgelassen per --preflight-skip: nur Doku" in (
        format_command_result(lint)
    )
    payload = json.loads((repo / report.artifact).read_text())
    assert payload["partial"] is True
    assert payload["commands"][1]["skip_reason"] == "nur Doku"
    assert payload["commands"][1]["status"] == "skipped"
    text = render_review_handoff(_issue(), report)
    assert PARTIAL_RUN_NOTE in text


def test_failed_check_in_partial_run_is_not_valid(tmp_path: Path):
    """Teillauf und Übergabefähigkeit sind getrennt: Eine rote Prüfung
    bleibt rot, auch wenn eine andere ausgelassen wurde."""
    repo = _repo(tmp_path)
    config = apply_preflight_options(
        PreflightConfig(
            corrections=(),
            checks=(
                _py("tests", "import sys; sys.exit(1)"),
                _py("lint", "pass"),
            ),
        ),
        {},
        {"lint": "nur Doku"},
    )
    report = run_preflight(config, repo)
    assert report.partial
    assert not report.valid


def test_full_run_is_not_partial_and_keeps_pass(tmp_path: Path):
    repo = _repo(tmp_path)
    config = PreflightConfig(corrections=(), checks=(_py("t", "pass"),))
    report = run_preflight(config, repo)
    assert report.valid
    assert not report.partial
    text = render_review_handoff(_issue(), report)
    assert PARTIAL_RUN_NOTE not in text
    payload = json.loads((repo / report.artifact).read_text())
    assert payload["partial"] is False
