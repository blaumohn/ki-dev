"""pre-push-Hook: README beim Push nach dev aktuell (bel0).

Fake-docker, -make und -bd im PATH; den echten Lauf deckt ein Push nach
dev auf dem Host ab.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from plumbum import local

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".beads/hooks/pre-push"
ZERO = "0" * 40
IDENTITY = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for name in ("README.md", "README.en.md"):
        (repo / name).write_text("alt\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    return repo


@pytest.fixture
def fake_bin(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _tool(bin_dir, "docker", "exit 0")
    _tool(bin_dir, "bd", 'cat >"$FAKE_BD_STDIN"')
    _tool(
        bin_dir,
        "make",
        'echo "$*" >"$FAKE_MAKE_CALLS"\n'
        'if [ -n "${FAKE_MAKE_WRITES:-}" ]; then\n'
        "  echo neu >README.md\n"
        "fi\n"
        'exit "${FAKE_MAKE_EXIT:-0}"',
    )
    return bin_dir


def test_push_to_other_branch_skips_check(repo, fake_bin, tmp_path):
    (fake_bin / "docker").unlink()
    code, _, _ = _push(repo, fake_bin, tmp_path, "refs/heads/main")
    assert code == 0
    assert not (tmp_path / "make.calls").exists()


def test_deleting_dev_skips_check(repo, fake_bin, tmp_path):
    code, _, _ = _push(repo, fake_bin, tmp_path, sha=ZERO)
    assert code == 0
    assert not (tmp_path / "make.calls").exists()


def test_clean_push_to_dev_runs_readme_check(repo, fake_bin, tmp_path):
    code, _, err = _push(repo, fake_bin, tmp_path)
    assert code == 0, err
    assert (tmp_path / "make.calls").read_text() == "readme-check\n"


def test_beads_section_still_reads_push_refs(repo, fake_bin, tmp_path):
    _push(repo, fake_bin, tmp_path, "refs/heads/main")
    sha = _head(repo)
    assert (tmp_path / "bd.stdin").read_text() == (
        f"refs/heads/main {sha} refs/heads/main {ZERO}\n"
    )


def test_without_docker_push_is_rejected(repo, fake_bin, tmp_path):
    _tool(fake_bin, "docker", "exit 1")
    code, _, err = _push(repo, fake_bin, tmp_path)
    assert code == 1
    assert "Docker fehlt" in err
    assert not (tmp_path / "make.calls").exists()


def test_untracked_file_is_rejected(repo, fake_bin, tmp_path):
    (repo / "notiz.txt").write_text("x\n")
    code, _, err = _push(repo, fake_bin, tmp_path)
    assert code == 1
    assert "Arbeitsbaum nicht sauber" in err


def test_pushed_commit_not_head_is_rejected(repo, fake_bin, tmp_path):
    old = _head(repo)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "zwei")
    code, _, err = _push(repo, fake_bin, tmp_path, sha=old)
    assert code == 1
    assert "nicht HEAD" in err


def test_failing_readme_check_is_rejected(repo, fake_bin, tmp_path):
    code, _, err = _push(repo, fake_bin, tmp_path, FAKE_MAKE_EXIT="2")
    assert code == 1
    assert "make readme-check fehlgeschlagen" in err


def test_changed_readme_is_rejected(repo, fake_bin, tmp_path):
    code, _, err = _push(repo, fake_bin, tmp_path, FAKE_MAKE_WRITES="1")
    assert code == 1
    assert "README aktualisiert: committen und erneut pushen" in err


def _push(
    repo, fake_bin, tmp_path, ref="refs/heads/dev", sha=None, **env
):
    sha = sha or _head(repo)
    refs = f"{ref} {sha} {ref} {ZERO}\n"
    with local.cwd(repo), local.env(
        PATH=f"{fake_bin}:/usr/bin:/bin",
        FAKE_BD_STDIN=str(tmp_path / "bd.stdin"),
        FAKE_MAKE_CALLS=str(tmp_path / "make.calls"),
        **env,
    ):
        hook = local["sh"][HOOK, "origin", "git@example.invalid:r.git"]
        return (hook << refs).run(retcode=None, timeout=30)


def _tool(bin_dir, name, body):
    tool = bin_dir / name
    tool.write_text(f"#!/bin/sh\n{body}\n")
    tool.chmod(0o755)


def _head(repo):
    return _git(repo, "rev-parse", "HEAD").strip()


def _git(repo, *args):
    with local.env(**IDENTITY):
        return local["git"].run(
            args=["-C", repo, *args], retcode=0, timeout=10
        )[1]
