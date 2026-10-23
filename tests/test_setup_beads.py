"""Setup ohne Downloads, Compiler oder Änderungen am System-bd."""

import os
import shutil
import sys
from pathlib import Path

import pytest
from plumbum import local

from ki_dev.tool_versions import load_tool_versions

ROOT = Path(__file__).resolve().parents[1]
PINS = load_tool_versions()
EXPECTED = f"bd version {PINS['BD_VERSION']} ({PINS['BD_COMMIT'][:7]})"


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo with spaces"
    (root / "scripts").mkdir(parents=True)
    (root / ".venv/bin").mkdir(parents=True)
    (root / "src/ki_dev").mkdir(parents=True)
    shutil.copy(ROOT / "Makefile", root)
    shutil.copy(ROOT / "scripts/setup_beads.py", root / "scripts")
    shutil.copy(
        ROOT / "src/ki_dev/tool-versions.json", root / "src/ki_dev"
    )
    modules = ("__init__.py", "tool_versions.py", "config_sources.py")
    for name in modules:
        shutil.copy(ROOT / "src/ki_dev" / name, root / "src/ki_dev")
    # Kein Symlink: Python sucht pyvenv.cfg neben dem aufgerufenen Pfad
    # und fiele sonst auf das System-Python ohne plumbum zurück.
    executable(
        root / ".venv/bin/python", f'exec "{sys.executable}" "$@"\n'
    )
    (root / ".venv/bin/ki-dev").touch()
    executable(
        root / "scripts/demo-mock-lauf.sh",
        "bd --version > demo-version\n",
    )
    system = root / "system"
    system.mkdir()
    executable(
        system / "git",
        """
echo "$*" >> "$CALLS"
if [ "$1" = rev-parse ]; then echo "$COMMIT"; fi
""",
    )
    executable(
        system / "go",
        """
echo "$*" >> "$CALLS"
[ "${BUILD_EXIT:-0}" = 0 ] || exit "$BUILD_EXIT"
while [ "$1" != -o ]; do shift; done
cp "$BUILD_BINARY" "$2"
""",
    )
    executable(root / "built-bd", f"echo '{EXPECTED}'\n")
    return root


def executable(path, body):
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)


def make(repo, target="setup", pythonpath="", **env):
    with local.env(
        PATH=f"{repo / 'system'}:/usr/bin:/bin",
        PYTHONPATH=pythonpath,
        CALLS=str(repo / "calls"),
        COMMIT=PINS["BD_COMMIT"],
        BUILD_BINARY=str(repo / "built-bd"),
        **env,
    ):
        return local["make"].run(
            args=["-s", "-C", str(repo), target],
            retcode=None,
            timeout=30,
        )


def test_checkout_pins_override_old_installed_package(repo, tmp_path):
    old = tmp_path / "old installation"
    package = old / "ki_dev"
    package.mkdir(parents=True)
    (package / "__init__.py").touch()
    (package / "tool_versions.py").write_text(
        "def load_tool_versions():\n"
        "    return {'BD_VERSION': '1.3.0'}\n"
    )
    executable(repo / "system/bd", f"echo '{EXPECTED}'\n")
    code, _, error = make(repo, "demo", pythonpath=str(old))
    assert code == 0, error
    assert (repo / "demo-version").read_text().strip() == EXPECTED
    assert not (repo / "calls").exists()


@pytest.mark.parametrize("location", ["system", ".venv/bin"])
@pytest.mark.parametrize(
    "revision", [PINS["BD_COMMIT"][:7], PINS["BD_COMMIT"]]
)
def test_matching_bd_is_reused_on_repeated_demo(
    repo, location, revision
):
    binary = repo / location / "bd"
    output = f"bd version {PINS['BD_VERSION']} ({revision})"
    executable(binary, f"echo '{output}'\n")
    # Ein neuerer Python-Einstieg darf keinen erneuten Build auslösen.
    os.utime(binary, (1000000000, 1000000000))
    for _ in range(2):
        code, _, error = make(repo, "demo")
        assert code == 0, error
        assert (repo / "demo-version").read_text().strip() == output
    assert not (repo / "calls").exists()
    assert binary.read_text() == f"#!/bin/sh\necho '{output}'\n"


def test_matching_system_bd_replaces_stale_local_link(repo):
    executable(
        repo / ".venv/bin/bd", "echo 'bd version 1.3.0 (0000000)'\n"
    )
    executable(repo / "system/bd", f"echo '{EXPECTED}'\n")
    code, _, error = make(repo)
    assert code == 0, error
    assert (repo / ".venv/bin/bd").resolve() == repo / "system/bd"
    assert not (repo / "calls").exists()


@pytest.mark.parametrize(
    "output",
    [
        None,
        "bd version 1.3.0 (0000000)",
        "bd version 1.2.0 (a22785e)",
        "bd version 1.3.0 (dev)",
    ],
)
def test_missing_or_wrong_build_installs_pinned_commit_once(
    repo, output
):
    if output:
        executable(repo / "system/bd", f"echo '{output}'\n")
    for _ in range(2):
        code, _, error = make(repo)
        assert code == 0, error
    calls = (repo / "calls").read_text()
    assert calls.count("build -tags") == 1
    assert (
        f"fetch --depth=1 {PINS['BD_REPOSITORY']} {PINS['BD_COMMIT']}"
        in calls
    )
    assert (repo / ".venv/bin/bd").read_bytes() == (
        repo / "built-bd"
    ).read_bytes()


@pytest.mark.parametrize(
    "body, message",
    [
        ("exit 17\n", "Exit 17"),
        ("echo 'ungültige Ausgabe'\n", "nicht erkennbar"),
    ],
)
def test_broken_version_probe_fails_without_installing(
    repo, body, message
):
    executable(repo / "system/bd", body)
    code, _, error = make(repo)
    assert code != 0
    assert message in error
    assert not (repo / "calls").exists()


@pytest.mark.parametrize(
    "failure", ["compiler", "wrong_build", "wrong_source"]
)
def test_failed_install_preserves_previous_binary_and_cleans_up(
    repo, failure
):
    target = repo / ".venv/bin/bd"
    executable(target, "echo 'bd version 1.3.0 (0000000)'\n")
    original = target.read_bytes()
    env = {}
    if failure == "compiler":
        env["BUILD_EXIT"] = "23"
    elif failure == "wrong_build":
        executable(
            repo / "built-bd", "echo 'bd version 1.3.0 (0000000)'\n"
        )
    else:
        executable(
            repo / "system/git",
            "echo 0000000000000000000000000000000000000000\n",
        )
    code, _, _ = make(repo, **env)
    assert code != 0
    assert target.read_bytes() == original
    assert not list(target.parent.glob(".bd-build-*"))
