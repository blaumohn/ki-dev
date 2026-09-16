from pathlib import Path

from hypothesis import assume, given
from hypothesis import strategies as st
from typer.testing import CliRunner

import ki_dev.cli
from ki_dev.cli import app
from ki_dev.loop_runtime import LoopRunResult
from ki_dev.machine import Phase

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


def test_loop_without_config_fails_visibly():
    result = runner.invoke(app, ["loop"])
    assert result.exit_code == 2
    assert "--config" in result.output


def test_resume_requires_run_id():
    result = runner.invoke(app, ["loop", "resume"])
    assert result.exit_code != 0
    assert "run_id" in result.output


def test_loop_cli_starts_configured_run(monkeypatch, tmp_path):
    config = tmp_path / "loop.json"
    config.write_text("{}")
    seen = {}

    def fake_start(path, *, run_id, runs_dir):
        seen.update(path=path, run_id=run_id, runs_dir=runs_dir)
        return LoopRunResult(
            "run-1",
            "ready_to_finalize",
            2,
            Phase.FREEZE_REVIEWED_RESULT,
        )

    monkeypatch.setattr(ki_dev.cli, "start_from_config", fake_start)
    result = runner.invoke(
        app,
        [
            "loop",
            "--config",
            str(config),
            "--run-id",
            "run-1",
            "--runs-dir",
            str(tmp_path / "runs"),
        ],
    )

    assert result.exit_code == 0
    assert '"status": "ready_to_finalize"' in result.output
    assert seen == {
        "path": config,
        "run_id": "run-1",
        "runs_dir": Path(tmp_path / "runs"),
    }


def test_resume_cli_passes_bound_answer(monkeypatch, tmp_path):
    seen = {}

    def fake_resume(run_id, *, runs_dir, answer, reconcile_result):
        seen.update(
            run_id=run_id,
            runs_dir=runs_dir,
            answer=answer,
            reconcile_result=reconcile_result,
        )
        return LoopRunResult(
            run_id, "waiting_decision", 1, Phase.WAITING_DECISION
        )

    monkeypatch.setattr(ki_dev.cli, "resume_run", fake_resume)
    result = runner.invoke(
        app,
        [
            "loop",
            "resume",
            "run-1",
            "--answer",
            "ja",
            "--runs-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert seen["answer"] == "ja"
    assert seen["run_id"] == "run-1"


@given(name=_lowercase)
def test_unknown_loop_subcommand_always_fails(name):
    assume(name != "resume")
    result = runner.invoke(app, ["loop", name])
    assert result.exit_code != 0
