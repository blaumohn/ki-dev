from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from ki_dev.handoff import HandoffIssue
from ki_dev.handoff_preflight import (
    ARTIFACT_DIR,
    CommandSpec,
    PreflightConfig,
    PreflightConfigError,
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
    assert "would-check" not in statuses


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
            _py(
                "literal", "import sys; sys.stdout.write('$HOME')"
            ),
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
        corrections=(
            _py("touch", "open('neu.txt', 'w').write('x')"),
        ),
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


def test_own_artifact_directory_is_excluded_from_fingerprint(
    tmp_path: Path,
):
    repo = _repo(tmp_path)
    config = _ok_config()
    first = run_preflight(config, repo)
    second = run_preflight(config, repo)
    assert first.source_fingerprint == second.source_fingerprint


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
