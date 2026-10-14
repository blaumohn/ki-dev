"""Übernahme des Arbeitsstands in tests/readme/user-flow.sh."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from plumbum import local

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tests/readme/user-flow.sh"
IDENTITY = {
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


@pytest.fixture(scope="module", autouse=True)
def _require_bash_44():
    _, version, _ = local["bash"].run(
        args=[
            "-c",
            'printf "%s %s" '
            '"${BASH_VERSINFO[0]}" "${BASH_VERSINFO[1]}"',
        ],
        retcode=0,
        timeout=10,
    )
    if tuple(map(int, version.split())) < (4, 4):
        pytest.skip("inherit_errexit benötigt Bash >= 4.4")


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / "source"
    repo.mkdir()
    git = local["git"]
    with local.env(**IDENTITY):
        git.run(args=["-C", repo, "init", "-q"], retcode=0, timeout=10)
        (repo / ".gitignore").write_text("*.log\n")
        (repo / "a.txt").write_text("alt\n")
        git.run(args=["-C", repo, "add", "-A"], retcode=0, timeout=10)
        git.run(
            args=["-C", repo, "commit", "-q", "-m", "start"],
            retcode=0,
            timeout=10,
        )
    (repo / "a.txt").write_text("neu\n")
    (repo / "neu" / "b.txt").parent.mkdir()
    (repo / "neu" / "b.txt").write_text("b\n")
    (repo / "c.log").write_text("ignoriert\n")
    return repo


def test_working_state_is_committed_in_clone_only(source, tmp_path):
    code, out, err = _prepare(source, tmp_path)
    assert code == 0, err
    staging = Path(out.split("STAGING=", 1)[1].strip())
    assert (staging / "a.txt").read_text() == "neu\n"
    assert (staging / "neu/b.txt").read_text() == "b\n"
    assert not (staging / "c.log").exists()
    status = _git(staging, "status", "--porcelain")
    assert status == ""
    assert _git(source, "status", "--porcelain").splitlines() == [
        " M a.txt",
        "?? neu/",
    ]


@pytest.mark.parametrize(
    "failing", ["diff", "apply", "ls-files", "add"]
)
def test_failed_step_aborts_transfer(source, tmp_path, failing):
    shim = tmp_path / "bin" / "git"
    shim.parent.mkdir()
    shim.write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do [ "$a" = "$FAIL_GIT" ] && exit 3; done\n'
        f'exec "{shutil.which("git")}" "$@"\n'
    )
    shim.chmod(0o755)
    path = f"{shim.parent}:{local.env['PATH']}"
    code, out, _ = _prepare(
        source, tmp_path, PATH=path, FAIL_GIT=failing
    )
    assert code != 0
    assert "STAGING=" not in out


def _prepare(source, tmp_path, **env):
    work = tmp_path / "work"
    work.mkdir()
    program = (
        'source "$1"; WORK_BASE="$2"; prepare_staging_repo "$3"; '
        'echo "STAGING=$staging_dir"'
    )
    with local.env(**env):
        return local["bash"].run(
            args=["-c", program, "_", SCRIPT, work, source],
            retcode=None,
            timeout=60,
        )


def _git(repo, *args):
    return local["git"].run(
        args=["-C", repo, *args], retcode=0, timeout=10
    )[1]
