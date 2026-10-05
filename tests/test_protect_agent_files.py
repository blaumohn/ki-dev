"""scripts/protect-agent-files.py: Schutz nur für leere Dateien."""

import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FILES = ("AGENTS.md", "CLAUDE.md")


def run(root, *args):
    return subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/protect-agent-files.py"),
            "--root",
            str(root),
            *args,
        ],
        capture_output=True,
        text=True,
        check=False,
    )


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def clone(tmp_path):
    """Wie ein frischer Klon: leere Dateien mit normalem Modus."""
    for name in FILES:
        (tmp_path / name).write_text("")
        (tmp_path / name).chmod(0o644)
    return tmp_path


def test_protect_sets_read_only_and_check_passes(clone):
    assert run(clone, "--check").returncode == 1
    assert run(clone).returncode == 0
    assert all(mode(clone / name) == 0o444 for name in FILES)
    assert run(clone, "--check").returncode == 0
    assert run(clone).returncode == 0  # idempotent


def test_check_changes_nothing(clone):
    run(clone, "--check")
    assert all(mode(clone / name) == 0o644 for name in FILES)


def test_read_only_file_rejects_plain_write(clone):
    run(clone)
    with pytest.raises(PermissionError):
        (clone / "AGENTS.md").write_text("x")


def test_non_empty_file_is_not_protected(clone):
    (clone / "CLAUDE.md").write_text("<!-- BEGIN BEADS -->\n")
    result = run(clone)
    assert result.returncode == 1
    assert "CLAUDE.md: nicht leer" in result.stderr
    assert mode(clone / "CLAUDE.md") == 0o644
    assert mode(clone / "AGENTS.md") == 0o444


def test_missing_file_is_reported(clone):
    (clone / "AGENTS.md").unlink()
    result = run(clone)
    assert result.returncode == 1
    assert "AGENTS.md: nicht lesbar" in result.stderr
