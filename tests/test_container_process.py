"""ki-dev startet Executor und Prüfbefehle über den Launcher (j3vc)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ki_dev.adapter.contract import RunTask
from ki_dev.adapter.executors import ClaudeCliAdapter, ContainerProcess
from ki_dev.adapter.executors import container as container_module
from ki_dev.adapter.executors.contract import (
    Effort,
    TurnRequest,
    TurnResult,
    TurnStatus,
)
from ki_dev.deltas import checkpoint_git_step
from ki_dev.flow_ops.implement.cli import _container_process
from ki_dev.flow_ops.implement.config import RunConfigError
from ki_dev.repository_evidence import (
    CheckCommand,
    RepositoryEvidenceCollector,
    _worktree_status,
)
from ki_dev.repository_finalization import _git

LAUNCHER = Path("/rt/agent-container")


def _result(status=TurnStatus.OK, stdout="", error=None):
    return TurnResult(
        status=status,
        exit_code=0 if status is TurnStatus.OK else 1,
        stdout=stdout,
        stderr="",
        argv=(),
        duration_s=0.0,
        error=error,
    )


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs))
        return _result()

    monkeypatch.setattr(container_module, "run_cli_turn", run)
    return seen


def test_cli_call_gets_launcher_workdir_and_only_call_env(calls):
    process = ContainerProcess(LAUNCHER)
    process(
        ["claude", "-p"],
        stdin="auftrag",
        timeout_s=5,
        cwd=Path("/repo/bau"),
        env={"B": "2", "A": "1"},
    )
    argv, kwargs = calls[0]
    name = argv[argv.index("--name") + 1]
    assert argv == [
        str(LAUNCHER),
        "--workdir",
        "/repo/bau",
        "--name",
        name,
        "--env",
        "A",
        "--env",
        "B",
        "run",
        "claude",
        "-p",
    ]
    assert kwargs["stdin"] == "auftrag"
    assert kwargs["env"] == {"B": "2", "A": "1"}
    assert "cwd" not in kwargs


def test_adapter_call_and_version_probe_run_in_container(calls):
    adapter = ClaudeCliAdapter(runner=ContainerProcess(LAUNCHER))
    request = TurnRequest(
        session_id="s",
        message="m",
        model="sonnet",
        effort=Effort.MEDIUM,
        workdir=Path("/repo/bau"),
        env={},
    )
    adapter.probe_executed_version(request, 1.0)
    adapter.send_turn(request)
    assert all(argv[0] == str(LAUNCHER) for argv, _ in calls)
    assert calls[0][0][-2:] == ["claude", "--version"]
    assert "--workdir" in calls[1][0]


def test_missing_workdir_is_refused(calls):
    with pytest.raises(ValueError, match="workdir"):
        ContainerProcess(LAUNCHER)(["claude"], stdin="")
    assert calls == []


def test_ok_needs_no_stop(calls):
    ContainerProcess(LAUNCHER)(["claude"], stdin="", cwd=Path("/w"))
    assert len(calls) == 1


def test_timeout_stops_the_named_container(monkeypatch):
    seen = []

    def run(argv, **_kwargs):
        seen.append(argv)
        if argv[1] == "stop":
            return _result()
        return _result(TurnStatus.TIMEOUT, error="Zeit")

    monkeypatch.setattr(container_module, "run_cli_turn", run)
    result = ContainerProcess(LAUNCHER)(
        ["claude"], stdin="", cwd=Path("/w")
    )
    assert result.status is TurnStatus.TIMEOUT
    name = seen[0][seen[0].index("--name") + 1]
    assert seen[1] == [str(LAUNCHER), "stop", name]


def test_interrupt_stops_the_container_and_stays_an_interrupt(
    monkeypatch,
):
    seen = []

    def run(argv, **_kwargs):
        seen.append(argv)
        if argv[1] == "stop":
            return _result()
        raise KeyboardInterrupt

    monkeypatch.setattr(container_module, "run_cli_turn", run)
    with pytest.raises(KeyboardInterrupt):
        ContainerProcess(LAUNCHER)(["claude"], stdin="", cwd=Path("/w"))
    assert seen[-1][1] == "stop"


def test_failed_stop_is_named_in_the_error(monkeypatch):
    def run(argv, **_kwargs):
        if argv[1] == "stop":
            return _result(TurnStatus.NONZERO_EXIT, error="docker weg")
        return _result(TurnStatus.TIMEOUT, error="Zeit")

    monkeypatch.setattr(container_module, "run_cli_turn", run)
    result = ContainerProcess(LAUNCHER)(
        ["claude"], stdin="", cwd=Path("/w")
    )
    assert "nicht entfernt: docker weg" in result.error
    assert result.error.startswith("Zeit")


def test_profile_without_table_stays_local():
    assert _container_process({}) is None


def test_profile_names_a_missing_launcher(tmp_path):
    missing = tmp_path / "fehlt"
    with pytest.raises(RunConfigError, match="make setup-runtime"):
        _container_process({"container": {"launcher": str(missing)}})


def test_profile_default_is_the_installed_launcher(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    launcher = (
        tmp_path / "ki-dev/agent-container/scripts/agent-container"
    )
    launcher.parent.mkdir(parents=True)
    launcher.write_text("")
    process = _container_process({"container": {}})
    assert process == ContainerProcess(launcher)


def test_checks_run_through_the_process(tmp_path):
    seen = []

    def process(argv, **kwargs):
        seen.append((argv, kwargs))
        return _result(TurnStatus.NONZERO_EXIT, stdout="rot", error="x")

    collector = RepositoryEvidenceCollector(process=process)
    task = RunTask(
        run_id="r",
        task="t",
        sources=(),
        workdir=tmp_path,
        access_profile="write",
        acceptance_criteria=("a",),
        env={"X": "1"},
    )
    outcome = collector._check(
        task, CheckCommand("t", ("pytest",), 7.0)
    )
    assert (outcome.passed, outcome.detail) == (False, "rot")
    assert seen[0][0] == ["pytest"]
    assert seen[0][1]["cwd"] == tmp_path
    assert seen[0][1]["timeout_s"] == 7.0
    assert seen[0][1]["env"] == {"X": "1"}


def _repo(path: Path) -> Path:
    path.mkdir()
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.name", "t"],
        ["config", "user.email", "t@example.invalid"],
    ):
        subprocess.run(["git", "-C", str(path), *args], check=True)
    (path / "a").write_text("1\n")
    subprocess.run(["git", "-C", str(path), "add", "a"], check=True)
    subprocess.run(
        ["git", "-C", str(path), "commit", "-qm", "start"], check=True
    )
    return path


def _plant(repo: Path, marker: Path) -> None:
    """Was ein Agent ohne Schreibschutz hinterlassen könnte."""
    script = repo / ".git/evil.sh"
    script.write_text(f"#!/bin/sh\n: > '{marker}'\n")
    script.chmod(0o755)
    hooks = repo / ".git/hooks"
    hooks.mkdir(exist_ok=True)
    for hook in (
        "pre-commit",
        "commit-msg",
        "post-commit",
        "post-merge",
    ):
        (hooks / hook).write_text(script.read_text())
        (hooks / hook).chmod(0o755)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "config",
            "core.fsmonitor",
            str(script),
        ],
        check=True,
    )


def test_host_git_runs_no_hook_and_no_fsmonitor(tmp_path):
    repo = _repo(tmp_path / "repo")
    marker = tmp_path / "ausgefuehrt"
    _plant(repo, marker)

    (repo / "a").write_text("2\n")
    assert _worktree_status(repo)
    checkpoint = checkpoint_git_step(repo, message="ki-dev").value
    subprocess.run(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            "-C",
            str(repo),
            "reset",
            "-q",
            "--hard",
            "HEAD~1",
        ],
        check=True,
    )
    marker.unlink(missing_ok=True)
    _git(repo, "merge", "--ff-only", checkpoint)

    assert not marker.exists()
    assert (repo / "a").read_text() == "2\n"


def test_plain_git_would_run_them(tmp_path):
    """Gegenprobe: ohne HOST_GIT läuft der gepflanzte Hook."""
    repo = _repo(tmp_path / "repo")
    marker = tmp_path / "ausgefuehrt"
    _plant(repo, marker)
    (repo / "a").write_text("2\n")
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-qam", "x"], check=False
    )
    assert marker.exists()
