from pathlib import Path

from typer.testing import CliRunner

from ki_dev import handoff_preflight, loop_cli, tool_versions
from ki_dev.cli import app
from ki_dev.config_cli import SOURCES

runner = CliRunner()


def _lines(tmp_path: Path, monkeypatch) -> dict[str, str]:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["BEFEHL", "ORT", "ABSCHNITT", "ZUSTAND"]
    by_command = {}
    for line in lines[1:]:
        # Längster passender Befehl: "loop" ist Präfix eines anderen.
        command = max(
            (s.command for s in SOURCES if line.startswith(s.command)),
            key=len,
        )
        by_command[command] = line
    return by_command


def test_config_lists_every_source_from_module_constants(
    tmp_path, monkeypatch
):
    """Orte stammen aus den zuständigen Modulen, nicht aus Kopien."""
    lines = _lines(tmp_path, monkeypatch)
    assert SOURCES == (
        handoff_preflight.CONFIG_SOURCE,
        loop_cli.CONFIG_SOURCE,
        tool_versions.CONFIG_SOURCE,
    )
    assert len(lines) == len(SOURCES)
    for source in SOURCES:
        assert source.location in lines[source.command]
        if source.section:
            assert source.section in lines[source.command]


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
