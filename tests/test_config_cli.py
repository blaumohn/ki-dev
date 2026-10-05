from pathlib import Path

from typer.testing import CliRunner

from ki_dev import (
    handoff_limit_config,
    handoff_next_turn,
    handoff_preflight,
    loop_cli,
    tool_versions,
)
from ki_dev.cli import app
from ki_dev.config_cli import SOURCES

runner = CliRunner()


def _lines(tmp_path: Path, monkeypatch) -> dict[str, str]:
    """Zeile je Befehl; breites Terminal, damit Rich nicht umbricht."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    header = ["Befehl", "Ort", "/", "Abschnitt", "Zustand"]
    assert lines[0].split() == header
    by_command = {}
    for line in lines[2:]:
        # Längster passender Befehl: "loop" ist Präfix eines anderen.
        matches = [
            s.command for s in SOURCES if line.startswith(s.command)
        ]
        if matches:
            by_command[max(matches, key=len)] = line.rstrip()
    return by_command


def _output(tmp_path: Path, monkeypatch) -> str:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    return runner.invoke(app, ["config"]).stdout


def test_config_lists_every_source_from_module_constants(
    tmp_path, monkeypatch
):
    """Orte stammen aus den zuständigen Modulen, nicht aus Kopien."""
    lines = _lines(tmp_path, monkeypatch)
    assert SOURCES == (
        handoff_preflight.CONFIG_SOURCE,
        handoff_limit_config.CONFIG_SOURCE,
        handoff_next_turn.CONFIG_SOURCE,
        loop_cli.CONFIG_SOURCE,
        tool_versions.CONFIG_SOURCE,
    )
    assert len(lines) == len(SOURCES)
    output = _output(tmp_path, monkeypatch)
    for source in SOURCES:
        assert source.location in lines[source.command]
        if source.section:
            # Abschnitt in eigener Zeile, wörtlich (nicht als Markup).
            assert f"[{source.section}]" in output


def test_config_reports_missing_and_present_project_file(
    tmp_path, monkeypatch
):
    command = handoff_preflight.CONFIG_SOURCE.command
    assert _lines(tmp_path, monkeypatch)[command].endswith("fehlt")
    (tmp_path / "pyproject.toml").write_text("")
    assert _lines(tmp_path, monkeypatch)[command].endswith("vorhanden")


def test_config_names_per_call_source_and_package_file(
    tmp_path, monkeypatch
):
    lines = _lines(tmp_path, monkeypatch)
    assert lines[loop_cli.CONFIG_SOURCE.command].endswith("je Aufruf")
    assert lines[tool_versions.CONFIG_SOURCE.command].endswith(
        "vorhanden"
    )


def test_config_writes_nothing(tmp_path, monkeypatch):
    _lines(tmp_path, monkeypatch)
    assert list(tmp_path.iterdir()) == []


def test_root_help_lists_config():
    result = runner.invoke(app, ["--help"])
    assert "config" in result.output
