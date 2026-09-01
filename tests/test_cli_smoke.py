from hypothesis import assume, given
from hypothesis import strategies as st
from typer.testing import CliRunner

from ki_dev.cli import app

runner = CliRunner()

_lowercase = st.text(
    alphabet=st.characters(min_codepoint=97, max_codepoint=122),
    min_size=1,
    max_size=8,
)


def test_root_help_lists_loop():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "loop" in result.output


def test_loop_help_lists_resume():
    result = runner.invoke(app, ["loop", "--help"])
    assert result.exit_code == 0
    assert "resume" in result.output


def test_loop_resume_help_runs():
    result = runner.invoke(app, ["loop", "resume", "--help"])
    assert result.exit_code == 0


def test_loop_without_wiring_fails_visibly():
    result = runner.invoke(app, ["loop"])
    assert result.exit_code == 1
    assert "noch nicht verkabelt" in result.output


def test_resume_without_wiring_fails():
    result = runner.invoke(app, ["loop", "resume"])
    assert result.exit_code == 1
    assert "noch nicht verkabelt" in result.output


@given(name=_lowercase)
def test_unknown_loop_subcommand_always_fails(name):
    assume(name != "resume")
    result = runner.invoke(app, ["loop", name])
    assert result.exit_code != 0
