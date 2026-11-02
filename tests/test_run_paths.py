"""Standardort der Laufdaten (ki-dev-ablauf-1vtn)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ki_dev.run_paths import default_runs_dir


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True)


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(
        path,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@e",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "start",
    )
    return path.resolve()


def test_uses_xdg_state_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    repo = _repo(tmp_path / "app")
    runs = default_runs_dir(repo)
    assert runs.parent == tmp_path / "state/ki-dev/runs"
    assert runs.name.startswith("app-")


def test_relative_xdg_value_counts_as_unset(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", "relativ")
    monkeypatch.setenv("HOME", str(tmp_path))
    runs = default_runs_dir(_repo(tmp_path / "app"))
    assert runs.parent == tmp_path / ".local/state/ki-dev/runs"


def test_repos_do_not_share_a_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    first = default_runs_dir(_repo(tmp_path / "a/app"))
    second = default_runs_dir(_repo(tmp_path / "b/app"))
    assert first != second


def test_worktree_shares_the_folder_of_its_repo(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    repo = _repo(tmp_path / "app")
    work = tmp_path / "app-work"
    _git(repo, "worktree", "add", "-q", "--detach", str(work), "main")
    assert default_runs_dir(work) == default_runs_dir(repo)


def test_outside_git_the_folder_itself_counts(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    plain = tmp_path / "ohne-git"
    plain.mkdir()
    assert default_runs_dir(plain).name.startswith("ohne-git-")
