"""Übernahme des Arbeitsstands in tests/readme/user-flow.sh."""

from __future__ import annotations

import re
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


def test_clone_url_from_setup_script_is_redirected(source, tmp_path):
    """Die Adresse aus 1-setup.sh klont offline den lokalen Stand."""
    _git(source, "add", "-A")
    with local.env(**IDENTITY):
        _git(source, "commit", "-q", "-m", "neu")
    scripts = tmp_path / "readme-scripts"
    scripts.mkdir()
    url = "https://github.com/example/ki-dev.git"
    (scripts / "1-setup.sh").write_text(f"git clone {url} ki-dev\n")
    program = (
        'source "$1"; README_SCRIPTS_DIR="$2"; '
        'redirect_clone_url "file://$3"; '
        'git clone -q "$4" "$5"; echo "COUNT=$GIT_CONFIG_COUNT"'
    )
    clone = tmp_path / "klon"
    with local.env(
        GIT_CONFIG_COUNT="1",
        GIT_CONFIG_KEY_0="safe.directory",
        GIT_CONFIG_VALUE_0="*",
    ):
        code, out, err = local["bash"].run(
            args=["-c", program, "_", SCRIPT, scripts, source, url,
                  clone],
            retcode=None,
            timeout=60,
        )
    assert code == 0, err
    assert "COUNT=2" in out
    assert (clone / "a.txt").read_text() == "neu\n"


def test_setup_script_without_clone_line_fails(tmp_path):
    scripts = tmp_path / "readme-scripts"
    scripts.mkdir()
    (scripts / "1-setup.sh").write_text('git clone "$URL" ki-dev\n')
    program = (
        'source "$1"; README_SCRIPTS_DIR="$2"; '
        'redirect_clone_url "file:///x"'
    )
    code, _, err = local["bash"].run(
        args=["-c", program, "_", SCRIPT, scripts],
        retcode=None,
        timeout=30,
    )
    assert code != 0
    assert "keine Zeile 'git clone URL ki-dev'" in err


def test_visitor_part_sets_no_git_identity():
    """Zwischen den Tests übernimmt user-flow.sh nur Verzeichnis und
    PATH; eine Identität nennt nur der Commit im temporären Klon."""
    text = SCRIPT.read_text()
    staging = re.search(
        r"^commit_working_state\(\) \{\n.*?^\}\n", text, re.M | re.S
    )
    assert staging
    rest = text.replace(staging.group(0), "")
    identity = (
        r"user\.(name|email)|\b(GIT_(AUTHOR|COMMITTER)_\w+|EMAIL)="
    )
    assert not re.search(identity, rest)
    main = re.search(r"^main\(\) \{\n.*?^\}\n", text, re.M | re.S)
    assert main
    body = main.group(0)
    assert 0 <= body.find("isolate_git_config") < body.find(
        "run_readme_test"
    )


def test_visitor_git_config_hides_host_identity(tmp_path):
    host = tmp_path / "host.gitconfig"
    host.write_text(
        "[user]\n\tname = host\n\temail = host@example.invalid\n"
    )
    empty = tmp_path / "leer.gitconfig"
    program = (
        'source "$1"; isolate_git_config "$2"; '
        "if git config user.name; then exit 3; fi; "
        'env | grep -E "^(GIT_(AUTHOR|COMMITTER)_|EMAIL=)" && exit 4; '
        'echo "GLOBAL=$GIT_CONFIG_GLOBAL NOSYSTEM=$GIT_CONFIG_NOSYSTEM"'
    )
    with local.cwd(tmp_path), local.env(
        GIT_CONFIG_GLOBAL=str(host),
        EMAIL="host@example.invalid",
        **IDENTITY,
    ):
        code, out, err = local["bash"].run(
            args=["-c", program, "_", SCRIPT, empty],
            retcode=None,
            timeout=30,
        )
    assert code == 0, (out, err)
    assert f"GLOBAL={empty} NOSYSTEM=1" in out
    assert empty.read_text() == ""


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

