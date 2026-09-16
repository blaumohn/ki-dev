"""Hermetische Test-Repositories fuer die Schrittdelta-Bildung.

Jeder Beads-Test laeuft in einer eigenen temporaeren Git-/Dolt-DB;
das Repository dieses Projekts wird nie beruehrt.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from plumbum import CommandNotFound, local


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
    )


def _init_git_repo(repo: Path) -> None:
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "ki-dev-test@example.invalid")
    _git(repo, "config", "user.name", "ki-dev test")
    (repo / "README.md").write_text("# Testfeld\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(
        repo, "commit", "-q", "--message", "Start (ki-dev-ablauf-8dd.3)"
    )


def _require_bd() -> None:
    try:
        local["bd"]
    except CommandNotFound:
        pytest.skip("bd lokal nicht installiert")


def run_bd(repo: Path, *args: str) -> str:
    """Fuehre ein ``bd``-Kommando im Test-Repository aus."""
    done = subprocess.run(
        ["bd", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "git-repo"
    repo.mkdir()
    _init_git_repo(repo)
    return repo


@pytest.fixture
def work_repo(tmp_path: Path) -> Path:
    _require_bd()
    repo = tmp_path / "work-repo"
    repo.mkdir()
    _init_git_repo(repo)
    subprocess.run(
        ["bd", "init", "--quiet", "--non-interactive"],
        check=True,
        capture_output=True,
        cwd=repo,
    )
    return repo
