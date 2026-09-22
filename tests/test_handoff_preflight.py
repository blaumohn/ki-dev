from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from ki_dev.handoff import HandoffIssue
from ki_dev.handoff_preflight import (
    ARTIFACT_DIR,
    CommandResult,
    CommandSpec,
    PreflightConfig,
    PreflightConfigError,
    PreflightExecutionError,
    format_command_result,
    load_preflight_config,
    render_review_handoff,
    run_preflight,
)


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


def test_command_of_exactly_100_chars_after_quoting_is_accepted(
    tmp_path: Path,
):
    """len(shlex.join(argv)) <= 100 ist die Grenze, nicht < 100
    (Vorlaufvertrag P2)."""
    argv = ["x" * 100]
    assert len(shlex.join(argv)) == 100
    _pyproject(
        tmp_path, f"checks = [{{name = 'c', argv = {argv!r}, "
        "timeout_s = 1.0}]\n",
    )
    config = load_preflight_config(tmp_path)
    assert config.checks[0].argv == tuple(argv)


def test_command_of_101_chars_after_quoting_is_config_error(
    tmp_path: Path,
):
    argv = ["x" * 101]
    assert len(shlex.join(argv)) == 101
    _pyproject(
        tmp_path, f"checks = [{{name = 'c', argv = {argv!r}, "
        "timeout_s = 1.0}]\n",
    )
    with pytest.raises(PreflightConfigError, match="100"):
        load_preflight_config(tmp_path)


def test_command_length_counts_quoting_not_just_plain_text(
    tmp_path: Path,
):
    """Ein Token mit Leerzeichen braucht Quoting; die Grenze gilt fuer
    len(shlex.join(argv)), nicht fuer eine naive Verkettung ohne
    Quoting -- sonst koennte ein Befehl die 100 Zeichen inklusive
    Quoting ueberschreiten, ohne dass die Pruefung es bemerkt."""
    argv = ["x" * 95, "a b"]
    plain_length = len(" ".join(argv))
    quoted_length = len(shlex.join(argv))
    assert plain_length <= 100 < quoted_length
    _pyproject(
        tmp_path, f"checks = [{{name = 'c', argv = {argv!r}, "
        "timeout_s = 1.0}]\n",
    )
    with pytest.raises(PreflightConfigError, match="100"):
        load_preflight_config(tmp_path)


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


def test_uncommitted_change_during_checks_invalidates_report(
    tmp_path: Path,
):
    """Eine Pruefung, die eine relevante Datei veraendert, macht den
    Bericht ungueltig, auch wenn ihr eigener Exitstatus 0 ist."""
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
    assert report.valid is False


def test_git_head_alone_is_not_enough_uncommitted_changes_bind_report(
    tmp_path: Path,
):
    repo = _repo(tmp_path)
    (repo / "README.md").write_text("uncommitted\n")
    config = _ok_config("noop")
    first = run_preflight(config, repo)
    (repo / "README.md").write_text("anders\n")
    second = run_preflight(config, repo)
    assert first.source_fingerprint != second.source_fingerprint


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
    assert payload["source_fingerprint"] == report.source_fingerprint
    assert payload["commands"][0]["name"] == "ok"
    assert payload["commands"][0]["argv"] == list(config.checks[0].argv)


def test_own_artifact_directory_is_excluded_from_fingerprint(
    tmp_path: Path,
):
    repo = _repo(tmp_path)
    config = _ok_config()
    first = run_preflight(config, repo)
    second = run_preflight(config, repo)
    assert first.source_fingerprint == second.source_fingerprint


# ---------------------------------------------------------------------
# _fingerprint: NUL-separierte git-status-Auswertung (Review P1)
# ---------------------------------------------------------------------


def test_fingerprint_changes_for_edit_of_quoted_path(tmp_path: Path):
    """Pfade mit Sonderzeichen quotiert git in der Textform (z. B.
    '"b \\303\\244.txt"'); ohne -z waere das kein gueltiger Dateipfad
    mehr und eine Aenderung koennte unbemerkt bleiben."""
    repo = _repo(tmp_path)
    quoted_path = repo / "b ä.txt"
    quoted_path.write_text("eins\n")
    config = _ok_config("noop")
    first = run_preflight(config, repo)
    quoted_path.write_text("zwei\n")
    second = run_preflight(config, repo)
    assert first.source_fingerprint != second.source_fingerprint


def test_fingerprint_changes_for_content_edit_after_rename(
    tmp_path: Path,
):
    """Ein Rename-Eintrag ('alt -> neu') ist in der Textform kein
    gueltiger Pfad; die NUL-getrennte Auswertung muss neuen und alten
    Pfad korrekt trennen und den tatsaechlichen Dateiinhalt hashen."""
    repo = _repo(tmp_path)
    (repo / "quelle.txt").write_text("eins\n")
    _git(repo, "add", "quelle.txt")
    _git(repo, "commit", "-q", "-m", "quelle")
    _git(repo, "mv", "quelle.txt", "ziel.txt")
    config = _ok_config("noop")
    first = run_preflight(config, repo)
    (repo / "ziel.txt").write_text("zwei\n")
    second = run_preflight(config, repo)
    assert first.source_fingerprint != second.source_fingerprint


def test_fingerprint_changes_for_edit_of_path_with_carriage_return(
    tmp_path: Path,
):
    """subprocess text=True uebersetzt \\r in \\n (Universal Newlines);
    ein Dateiname mit echtem \\r wuerde dann als nicht existierender
    Pfad mit \\n gelesen und Inhaltsaenderungen blieben unbemerkt."""
    repo = _repo(tmp_path)
    cr_path = repo / "a\rb.txt"
    cr_path.write_bytes(b"eins")
    config = _ok_config("noop")
    first = run_preflight(config, repo)
    cr_path.write_bytes(b"zwei")
    second = run_preflight(config, repo)
    assert first.source_fingerprint != second.source_fingerprint


def test_fingerprint_frames_path_and_content_without_ambiguity(
    tmp_path: Path,
):
    """Ohne Laengenpraefix waeren Pfad 'a' mit Inhalt 'bc' und Pfad
    'ab' mit Inhalt 'c' im Hasher ununterscheidbar (beide ergeben nach
    Verkettung von code+pfad+inhalt dieselbe Bytefolge 'abc'); mit
    echtem git status -z gegen die alte Verkettung reproduziert."""
    repo = _repo(tmp_path)
    config = _ok_config("noop")
    (repo / "a").write_bytes(b"bc")
    first = run_preflight(config, repo)
    (repo / "a").unlink()
    (repo / "ab").write_bytes(b"c")
    second = run_preflight(config, repo)
    assert first.source_fingerprint != second.source_fingerprint


# ---------------------------------------------------------------------
# Ausführungsfehler außerhalb einzelner Befehle (Review P2)
# ---------------------------------------------------------------------


def test_missing_git_repo_raises_execution_error_not_raw_exception(
    tmp_path: Path,
):
    """Kein Git-Repository: der Fingerprint schlägt fehl. Das muss als
    PreflightExecutionError sichtbar werden, nicht als unbehandelter
    CalledProcessError aus run_preflight heraus."""
    config = _ok_config()
    with pytest.raises(PreflightExecutionError):
        run_preflight(config, tmp_path)


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
    ersetzten Detail führen, nicht zu einem UnicodeDecodeError."""
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


def test_git_status_with_non_utf8_filename_fails_closed(tmp_path: Path):
    """Ein Dateiname mit ungültigen UTF-8-Bytes darf den Fingerprint
    nicht lautlos verfälschen (das wäre mit errors="replace" möglich:
    zwei verschiedene Zustände könnten auf denselben Fingerprint
    abbilden). Der Vorlauf muss stattdessen kontrolliert scheitern,
    nicht heimlich mit ersetztem Text weiterlaufen (Review-Befund
    AC4)."""
    repo = _repo(tmp_path)
    bad_name = os.fsdecode(b"bad-\xff\xfe.txt")
    (repo / bad_name).write_bytes(b"x")
    config = _ok_config()
    with pytest.raises(PreflightExecutionError, match="UTF-8"):
        run_preflight(config, repo)


def test_non_utf8_filename_error_tells_user_to_rename(tmp_path: Path):
    """Der Fehlertext muss ausdrücklich zum Umbenennen des betroffenen
    Pfads auffordern, nicht nur den Dekodierfehler nennen."""
    repo = _repo(tmp_path)
    bad_name = os.fsdecode(b"bad-\xff\xfe.txt")
    (repo / bad_name).write_bytes(b"x")
    config = _ok_config()
    with pytest.raises(PreflightExecutionError, match="umbenennen"):
        run_preflight(config, repo)


def test_execution_error_keeps_already_run_correction_results(
    tmp_path: Path,
):
    """Scheitert der Fingerprint (kein Git-Repo o. Ä.) nach bereits
    gelaufenen Korrekturen, müssen deren Ergebnisse am Fehler hängen
    bleiben statt verworfen zu werden -- sonst erfährt niemand von
    bereits erfolgten, nicht zurückgesetzten Änderungen."""
    repo = _repo(tmp_path)
    config = PreflightConfig(
        corrections=(_py("touched", "open('x.txt','w').write('x')"),),
        checks=(_py("ok", "pass"),),
    )
    run_preflight(config, repo)  # baseline: legt Artefaktordner an
    # Git unbenutzbar machen, ohne die Korrektur zu verhindern.
    (repo / ".git").rename(repo / ".git-weg")
    with pytest.raises(PreflightExecutionError) as excinfo:
        run_preflight(config, repo)
    names = [item.name for item in excinfo.value.partial_results]
    assert "touched" in names
    assert excinfo.value.partial_results[0].status == "pass"


def test_format_command_result_bounds_name_and_cleans_ansi():
    """name kommt aus der Konfiguration, nicht aus Prozessausgabe,
    unterliegt im Bericht aber derselben Bereinigungs-/Begrenzungs-
    pflicht wie bounded_detail (Review-Befund AC3). argv ist bereits
    beim Konfigurationsladen auf höchstens 100 Zeichen begrenzt und
    wird deshalb hier vollständig gezeigt, nur von ANSI-Codes
    bereinigt."""
    item = CommandResult(
        "x" * 5000,
        ("\x1b[31mtrue",),
        "pass",
        0,
        "",
        omitted=False,
    )
    line = format_command_result(item)
    assert "\x1b" not in line
    assert len(line) < 1000


def test_format_command_result_shows_valid_argv_completely():
    """Gültige argv sind beim Konfigurationsladen bereits auf höchstens
    100 Zeichen begrenzt; der Bericht zeigt sie deshalb vollständig,
    ohne Interpreterlisten, Optionsparser oder Maskierung."""
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


def _issue() -> HandoffIssue:
    return HandoffIssue(
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
    assert f"PRUEFBERICHT git={report.source_fingerprint}" in text
    assert "- ok: PASS" in text
    assert "[argv=" in text


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

    monkeypatch.setattr(subprocess, "run", _forbidden)
    render_review_handoff(_issue(), report)
