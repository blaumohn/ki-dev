"""Startskript der Agent-Sandbox: Mount-Auswahl, Ersatzpfade, Build."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest
from plumbum import local

ROOT = Path(__file__).resolve().parents[1]

FAKE_DOCKER = """#!/bin/sh
if [ "$1 $2" = "buildx version" ]; then exit 0; fi
printf '%s\\n' "$@" > "$FAKE_LOG/args"
printf '%s\\n' "${KI_DEV_CLAUDE_STATE-<unset>}" > "$FAKE_LOG/claude"
printf '%s\\n' "${KI_DEV_AGENT_BEADS_REPO-<unset>}" > "$FAKE_LOG/beads"
if [ "$1 $2" = "buildx build" ]; then
  for context; do :; done
  printf '%s\\n' "$context" > "$FAKE_LOG/context"
  (cd "$context" && find . -type f | sort) > "$FAKE_LOG/files"
fi
"""


@dataclass
class Sandbox:
    repo: Path
    auth: Path
    bin: Path
    log: Path
    config: Path

    @property
    def mounts(self):
        return self.config / "ki-dev/agent-container/mounts"

    def add_mount(self, name):
        self.mounts.mkdir(parents=True, exist_ok=True)
        (self.mounts / f"{name}.yaml").write_text(
            f"services:\n  agent:\n    volumes:\n"
            f"      - type: bind\n        source: /src/{name}\n"
            f"        target: /{name}\n"
        )

    def run(self, *args, retcode=0, env=None):
        variables = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "HOME": str(self.auth),
            "KI_DEV_AGENT_AUTH_HOME": str(self.auth),
            "FAKE_LOG": str(self.log),
            "XDG_CONFIG_HOME": str(self.config),
            **(env or {}),
        }
        assignments = [
            f"{key}={value}" for key, value in variables.items()
        ]
        script = str(self.repo / "scripts/agent-container")
        with local.cwd(self.repo):
            return local["/usr/bin/env"].run(
                args=["-i", *assignments, "/bin/bash", script, *args],
                retcode=retcode,
                timeout=10,
            )

    def logged(self, name):
        return (self.log / name).read_text().splitlines()

    def add_executable(self, path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"#!/bin/sh\n{body}\n")
        path.chmod(0o755)


@pytest.fixture
def sandbox(tmp_path):
    repo = tmp_path / "work" / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(ROOT / "scripts/agent-container", repo / "scripts")
    (repo / "docker/agent").mkdir(parents=True)
    (repo / "docker/agent/Dockerfile").write_text("FROM scratch\n")
    (repo / "src/ki_dev").mkdir(parents=True)
    (repo / "src/ki_dev/__init__.py").write_text("")
    (repo / "pyproject.toml").write_text("")
    auth = tmp_path / "auth"
    (auth / ".claude").mkdir(parents=True)
    (auth / ".codex").mkdir()
    log = tmp_path / "log"
    log.mkdir()
    box = Sandbox(
        repo, auth, tmp_path / "bin", log, tmp_path / "config"
    )
    for name in (
        "devkit",
        "mdman",
        "mdman-ai-session",
        "lebenslauf-web-vorlage",
    ):
        box.add_mount(name)
    box.add_executable(
        box.bin / "docker", FAKE_DOCKER.split("\n", 1)[1]
    )
    return box


def compose_files(args):
    return [args[i + 1] for i, arg in enumerate(args) if arg == "-f"]


def mount_file(sandbox, name):
    return str(sandbox.mounts / f"{name}.yaml")


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--mount", "nope"], "unknown mount 'nope' in "),
        (["-m", "mdm"], "ambiguous mount 'mdm': "),
        (["--mount"], "--mount needs NAME[,NAME...]"),
        (["--mount=../x"], "invalid mount list '../x'"),
        (["-m", "devkit,,mdman"], "invalid mount list"),
        (["-m", "devkit,"], "invalid mount list"),
        (["--verbose"], "unknown option '--verbose'"),
        (["bogus"], "unknown command 'bogus'"),
        (["run"], "run requires a command"),
    ],
)
def test_usage_errors(sandbox, args, message):
    _, _, stderr = sandbox.run(*args, retcode=2)
    assert f"agent-container: {message}" in stderr
    assert "--help" in stderr
    assert not (sandbox.log / "args").exists()


def test_help_is_static(sandbox):
    _, stdout, _ = sandbox.run("--help")
    assert "-m, --mount NAME[,NAME...]" in stdout
    assert "ki-dev/agent-container/mounts/NAME.yaml" in stdout
    assert "devkit" not in stdout
    assert not (sandbox.log / "args").exists()


def test_mounts_lists_names_and_targets(sandbox):
    _, stdout, _ = sandbox.run("mounts")
    lines = stdout.splitlines()
    assert lines[0] == f"Mount files in {sandbox.mounts}:"
    assert sorted(line.split() for line in lines[1:]) == [
        [name, f"/{name}", "<-", f"/src/{name}"]
        for name in (
            "devkit",
            "lebenslauf-web-vorlage",
            "mdman",
            "mdman-ai-session",
        )
    ]
    assert not (sandbox.log / "args").exists()


@pytest.mark.parametrize(
    ("state", "message"),
    [("missing", "(directory missing;"), ("empty", "(no mount files;")],
)
def test_mounts_without_files(sandbox, state, message):
    shutil.rmtree(sandbox.mounts)
    if state == "empty":
        sandbox.mounts.mkdir()
    _, stdout, _ = sandbox.run("mounts")
    assert stdout.splitlines()[1] == (
        f"  {message} template: docker/agent/mount.example.yaml)"
    )
    _, _, stderr = sandbox.run("-m", "devkit", "shell", retcode=2)
    assert f"unknown mount 'devkit' in {sandbox.mounts}" in stderr


def test_mount_dir_defaults_to_home_config(sandbox):
    home_mounts = sandbox.auth / ".config/ki-dev/agent-container/mounts"
    home_mounts.mkdir(parents=True)
    (home_mounts / "only-home.yaml").write_text("")
    sandbox.run(
        "-m", "only-home", "run", "true", env={"XDG_CONFIG_HOME": ""}
    )
    assert compose_files(sandbox.logged("args"))[1] == str(
        home_mounts / "only-home.yaml"
    )


@pytest.mark.parametrize(
    "options",
    [
        ["--mount", "devkit", "--mount", "mdman"],
        ["-m", "devkit,mdman"],
        ["--mount=dev", "-m", "mdman,devkit"],
    ],
)
def test_selected_mounts_follow_compose_yaml(sandbox, options):
    sandbox.run(*options, "run", "true")
    args = sandbox.logged("args")
    assert compose_files(args) == [
        str(sandbox.repo / "compose.yaml"),
        mount_file(sandbox, "devkit"),
        mount_file(sandbox, "mdman"),
    ]
    assert args[-2:] == ["agent", "true"]


def test_unique_prefix_selects_mount(sandbox):
    sandbox.run("-m", "mdman-ai,lebens", "run", "true")
    assert compose_files(sandbox.logged("args"))[1:] == [
        mount_file(sandbox, "mdman-ai-session"),
        mount_file(sandbox, "lebenslauf-web-vorlage"),
    ]


def test_shell_starts_bash_with_arguments(sandbox):
    sandbox.run("shell", "-lc", "pwd")
    assert sandbox.logged("args")[-3:] == ["bash", "-lc", "pwd"]


@pytest.mark.parametrize("source", ["sibling", "variable", "absent"])
def test_beads_mount(sandbox, source):
    beads = sandbox.repo.parent / "beads"
    env = {}
    if source == "sibling":
        beads.mkdir()
    elif source == "variable":
        beads = sandbox.repo.parent / "elsewhere"
        env["KI_DEV_AGENT_BEADS_REPO"] = str(beads)
    sandbox.run("run", "true", env=env)
    beads_file = str(sandbox.repo / "compose.beads.yaml")
    if source == "absent":
        assert beads_file not in compose_files(sandbox.logged("args"))
        assert sandbox.logged("beads") == ["<unset>"]
    else:
        assert compose_files(sandbox.logged("args"))[-1] == beads_file
        assert sandbox.logged("beads") == [str(beads)]


@pytest.mark.parametrize("present", [True, False])
def test_claude_state_only_when_present(sandbox, present):
    state = sandbox.auth / ".claude.json"
    if present:
        state.write_text("{}")
    sandbox.run(
        "run", "true", env={"KI_DEV_CLAUDE_STATE": "/inherited"}
    )
    expected = str(state) if present else "<unset>"
    assert sandbox.logged("claude") == [expected]


@pytest.mark.parametrize("missing", [".claude", ".codex"])
def test_missing_cli_login_fails(sandbox, missing):
    (sandbox.auth / missing).rmdir()
    _, _, stderr = sandbox.run("shell", retcode=1)
    assert f"Missing {sandbox.auth / missing}" in stderr
    assert not (sandbox.log / "args").exists()


def test_refuses_inside_container(sandbox):
    _, _, stderr = sandbox.run(
        "shell", retcode=1, env={"KI_DEV_AGENT_CONTAINER": "1"}
    )
    assert "already running inside the agent container" in stderr
    assert not (sandbox.log / "args").exists()


def fake_python(sandbox, path, value):
    sandbox.add_executable(path, f"printf '%s\\n' --build-arg {value}")


def test_build_prefers_project_venv(sandbox):
    fake_python(sandbox, sandbox.repo / ".venv/bin/python", "FROM=venv")
    fake_python(sandbox, sandbox.bin / "python3", "FROM=system")
    sandbox.run("build")
    args = sandbox.logged("args")
    assert args[:4] == ["buildx", "build", "--build-arg", "FROM=venv"]


def test_build_falls_back_to_system_python(sandbox):
    fake_python(sandbox, sandbox.bin / "python3", "FROM=system")
    sandbox.run("build")
    args = sandbox.logged("args")
    assert args[:4] == ["buildx", "build", "--build-arg", "FROM=system"]
    assert args[-3:-1] == [
        "-f",
        sandbox.logged("context")[0] + "/docker/agent/Dockerfile",
    ]
    assert sandbox.logged("files") == [
        "./docker/agent/Dockerfile",
        "./project/pyproject.toml",
        "./project/src/ki_dev/__init__.py",
    ]
    assert not Path(sandbox.logged("context")[0]).exists()


def test_build_stops_when_versions_fail(sandbox):
    sandbox.add_executable(sandbox.bin / "python3", "exit 1")
    sandbox.run("build", retcode=1)
    assert not (sandbox.log / "args").exists()
