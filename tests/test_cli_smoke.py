from pathlib import Path

import pytest
from typer.testing import CliRunner

import ki_dev.flow_ops.implement.commands as implement_ops
from ki_dev.cli import app, main
from ki_dev.flow import model
from ki_dev.flow_ops.implement.machine import Phase
from ki_dev.flow_ops.implement.runtime import RunResult

runner = CliRunner()


def _main(capsys, *args):
    with pytest.raises(SystemExit) as raised:
        main(list(args))
    out, err = capsys.readouterr()
    return raised.value.code, out, err


def test_root_help_names_flow_option_and_no_run_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ki-dev -f NAME" in result.output
    assert "│ run " not in result.output
    assert "loop" not in result.output


def test_flow_help_lists_package_commands(capsys):
    code, out, err = _main(capsys, "-f", "implement", "--help")
    assert code == 0
    for command in ("start", "resume", "status"):
        assert command in out
    assert "implement.toml" in err


def test_flow_option_needs_a_name(capsys):
    code, _, err = _main(capsys, "-f")
    assert code == 2
    assert "Namen" in err


def test_unknown_flow_names_every_place_searched(
    capsys, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("KI_DEV_FLOW_PATH", "/nirgends")
    code, _, err = _main(capsys, "-f", "nix")
    assert code == 2
    assert "nix.toml" in err and "/nirgends" in err


def test_flow_without_ops_is_data_only(capsys):
    code, _, err = _main(capsys, "-f", "map", "x")
    assert code == 2
    assert "kein ops-Modul" in err


def test_flow_file_in_cwd_wins_and_must_match_bound_flow(
    capsys, monkeypatch, tmp_path
):
    shipped = Path(model.__file__).parent
    text = (shipped / "implement.toml").read_text(encoding="utf-8")
    (tmp_path / "implement.toml").write_text(
        text.replace("nur der Mensch kann entscheiden", "anders"),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    code, _, err = _main(capsys, "-f", "implement", "--help")
    assert code == 2
    assert str(tmp_path / "implement.toml") in err
    assert "weicht vom mitgelieferten" in err


PROFILE = """\
workdir = "/work"
access_profile = "write"

[finalization]
target_workdir = "/ziel"
target_ref = "refs/heads/main"
commit_message = "Abschluss"
data_mode = "file_proposal"

[worker]
executor = "claude"
session_id = "w"
model = "m"
effort = "low"

[review]
executor = "codex"
session_id = "r"
model = "m"
effort = "low"
"""


def _fake_start(monkeypatch, seen):
    def fake(config, *, run_id, runs_dir, wrap, profile):
        seen.update(
            config=config,
            run_id=run_id,
            runs_dir=runs_dir,
            profile=profile.ref(),
        )
        return RunResult("run-1", "passed", 1, Phase.PASSED)

    monkeypatch.setattr(implement_ops, "start_run", fake)
    monkeypatch.setattr(
        implement_ops,
        "_bead_task",
        lambda bead, _cwd: {"task": f"Auftrag {bead}"},
    )


def test_bead_starts_run_with_profile_and_adapter_override(
    capsys, monkeypatch, tmp_path
):
    profile = tmp_path / ".ki-dev" / "profiles" / "default.toml"
    profile.parent.mkdir(parents=True)
    profile.write_text(PROFILE, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    seen: dict = {}
    _fake_start(monkeypatch, seen)

    code, out, _ = _main(
        capsys, "-f", "implement", "p-1", "--adapter", "review=manual"
    )

    assert code == 0
    assert '"status": "passed"' in out
    assert seen["config"]["worker"]["executor"] == "claude"
    assert seen["config"]["review"] == {"executor": "manual"}
    assert seen["config"]["task"] == "Auftrag p-1"
    assert seen["runs_dir"] == Path(".ki-dev/runs")
    assert seen["profile"]["path"] == str(profile)
    assert len(seen["profile"]["sha256"]) == 64


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("claude", "im Profil"),
        ("review=claude", "nur inbox, manual, mock"),
        ("planner=manual", "Rolle"),
    ],
)
def test_adapter_argument_rejects_session_adapters_and_roles(
    capsys, monkeypatch, tmp_path, value, message
):
    (tmp_path / "p.toml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    _fake_start(monkeypatch, {})
    code, _, err = _main(
        capsys,
        "-f", "implement", "p-1", "--profile", "p.toml",
        "--adapter", value,
    )
    assert code == 2
    assert message in err


def test_profile_must_not_carry_the_task(capsys, monkeypatch, tmp_path):
    (tmp_path / "p.toml").write_text('task = "x"\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    code, _, err = _main(
        capsys, "-f", "implement", "p-1", "--profile", "p.toml"
    )
    assert code == 2
    assert "aus dem Bead" in err


def test_resume_passes_bound_answer(capsys, monkeypatch, tmp_path):
    seen = {}

    def fake_resume(
        run_id, *, runs_dir, answer, reconcile_result, wrap, overrides
    ):
        seen.update(run_id=run_id, answer=answer, overrides=overrides)
        return RunResult(
            run_id, "waiting_decision", 1, Phase.WAITING_DECISION
        )

    monkeypatch.setattr(implement_ops, "resume_run", fake_resume)
    code, _, _ = _main(
        capsys,
        "-f", "implement", "resume", "run-1",
        "--answer", "ja", "--runs-dir", str(tmp_path),
        "--adapter", "review=manual",
    )
    assert code == 0
    assert seen == {
        "run_id": "run-1",
        "answer": "ja",
        "overrides": {"review": {"executor": "manual"}},
    }
