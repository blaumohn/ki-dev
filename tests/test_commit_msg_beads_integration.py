"""Belegt, dass ein vom Hook akzeptierter Titel auch real von Beads
erkannt wird (ki-dev-ablauf-rrd, Nachreview).

`bd orphans` erkennt referenzierte Issues ueber ein eigenes Muster
(``\\(<praefix>-[a-z0-9.]+\\)`` je Treffer, siehe
commit_msg.py-Docstring). Ein von ``validate_subject`` akzeptierter
Titel, der bd trotzdem nicht erkennt, waere eine stille
Falschbehauptung ("Beads-Integration") ohne Wirkung. Dieser Test
schliesst zwei echte, offene Issues gegen zwei echte Commit-Titel ab
(Komma- vs. Klammer-je-ID-Format) und liest den tatsaechlichen
`bd orphans --json`-Befund, kein Mock.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from plumbum import CommandNotFound, local

from ki_dev.commit_msg import ISSUE_PREFIX, validate_subject


def _bd_available() -> bool:
    try:
        local["bd"]
    except CommandNotFound:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _bd_available(), reason="bd lokal nicht installiert"
)


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _git(repo: Path, *args: str) -> None:
    _run(repo, "git", "-C", str(repo), *args)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "worktree"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@example.invalid")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "base")
    _run(
        repo,
        "bd",
        "init",
        "--prefix",
        ISSUE_PREFIX,
        "--quiet",
        "--non-interactive",
    )
    return repo


def _create_issue(repo: Path, title: str) -> str:
    result = _run(
        repo, "bd", "create", title, "--type", "task", "--json"
    )
    return json.loads(result.stdout)["id"]


def _orphan_ids(repo: Path) -> set[str]:
    result = _run(repo, "bd", "orphans", "--json")
    stdout = result.stdout.strip()
    payload = json.loads(stdout) if stdout else None
    if not payload:
        return set()
    return {entry["issue_id"] for entry in payload}


def test_hook_accepted_multi_id_title_is_recognized_by_bd(tmp_path):
    """Ein vom Hook akzeptierter Mehrfach-ID-Titel muss beide Issues bei
    ``bd orphans`` als referenziert ausweisen."""
    repo = _init_repo(tmp_path)
    issue_a = _create_issue(repo, "Testissue A")
    issue_b = _create_issue(repo, "Testissue B")

    subject = f"chore: zwei Issues schliessen ({issue_a}) ({issue_b})"
    assert validate_subject(subject) is None, (
        "Hook sollte dieses Format akzeptieren"
    )

    _git(repo, "commit", "-q", "--allow-empty", "-m", subject)

    assert _orphan_ids(repo) == {issue_a, issue_b}


def test_hook_rejected_comma_title_is_not_recognized_by_bd(tmp_path):
    """Das vom Hook abgelehnte Komma-Kurzformat verknuepft bei bd
    tatsaechlich kein einziges Issue -- Beleg fuer den urspruenglichen
    Befund, nicht nur Theorie."""
    repo = _init_repo(tmp_path)
    issue_a = _create_issue(repo, "Testissue A")
    issue_b = _create_issue(repo, "Testissue B")

    subject = f"chore: zwei Issues schliessen ({issue_a}, {issue_b})"
    assert validate_subject(subject) is not None, (
        "Hook sollte dieses Format ablehnen"
    )

    _git(repo, "commit", "-q", "--allow-empty", "-m", subject)

    assert _orphan_ids(repo) == set()
