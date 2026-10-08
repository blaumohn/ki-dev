"""Startskript der Agent-Sandbox: Mount-Auswahl, Modi, reset, Build."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from plumbum import local

from tests.test_agent_container_docker import docker_requested

ROOT = Path(__file__).resolve().parents[1]

FAKE_DOCKER = """#!/bin/sh
if [ "$1 $2" = "buildx version" ]; then exit 0; fi
if [ "$1" = volume ]; then
  echo "$*" >> "$FAKE_LOG/volume-calls"
  case "$2 $5" in
    "ls label="*) cat "$FAKE_LOG/volumes-${5#label=}" 2>/dev/null ;;
    "ls "*) cat "$FAKE_LOG/volumes" 2>/dev/null ;;
    "rm "*) exit "$(cat "$FAKE_LOG/rm-exit" 2>/dev/null || echo 0)" ;;
  esac
  exit 0
fi
for arg; do
  if [ "$arg" = config ]; then
    printf '%s\\n' "$@" >> "$FAKE_LOG/config-args"
    while [ $# -gt 0 ]; do
      if [ "$1" = -f ]; then file="$2"; fi
      shift
    done
    name="${file##*/}"
    cat "$FAKE_LOG/${name%.yaml}.json" 2>/dev/null || echo '{}'
    exit 0
  fi
done
printf '%s\\n' "$@" > "$FAKE_LOG/args"
printf '%s\\n' "${KI_DEV_CLAUDE_STATE-<unset>}" > "$FAKE_LOG/claude"
printf '%s\\n' "${KI_DEV_AGENT_BEADS_REPO-<unset>}" > "$FAKE_LOG/beads"
printf '%s\\n' "${KI_DEV_AGENT_CACHE_DIR-<unset>}" > "$FAKE_LOG/cache"
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
    cache: Path

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
            "XDG_CACHE_HOME": str(self.cache),
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
    for module in ("agent_repo_contract.py", "agent_dev_volumes.py"):
        shutil.copy(ROOT / "src/ki_dev" / module, repo / "src/ki_dev")
    (repo / "pyproject.toml").write_text("")
    auth = tmp_path / "auth"
    (auth / ".claude").mkdir(parents=True)
    (auth / ".codex").mkdir()
    log = tmp_path / "log"
    log.mkdir()
    box = Sandbox(
        repo,
        auth,
        tmp_path / "bin",
        log,
        tmp_path / "config",
        tmp_path / "cache",
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
    # A wrapper, not a symlink: build tests overwrite this file.
    box.add_executable(
        repo / ".venv/bin/python", f'exec "{sys.executable}" "$@"'
    )
    return box


def compose_files(args):
    return [args[i + 1] for i, arg in enumerate(args) if arg == "-f"]


def mount_file(sandbox, name):
    return str(sandbox.mounts / f"{name}.yaml")


def overlay_files(sandbox, args):
    overlay_dir = sandbox.cache / "agent-container/compose"
    return [
        path
        for path in compose_files(args)
        if Path(path).parent == overlay_dir
    ]


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--mount", "nope"], "unknown mount 'nope' in "),
        (["-m", "mdm"], "ambiguous mount 'mdm': "),
        (["--mount"], "--mount needs NAME[,NAME...]"),
        (["--mount-ro"], "--mount-ro benötigt DIR"),
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


@pytest.mark.parametrize("fresh", [[], ["--fresh"]])
def test_read_only_reference_directories(sandbox, fresh):
    first = sandbox.repo.parent / "example repo"
    second = sandbox.repo.parent / "docs,notes"
    first.mkdir()
    second.mkdir()
    sandbox.run(
        *fresh, "--mount-ro", "../example repo",
        f"--mount-ro={second}", "--mount-ro", str(first),
        "run", "ls", "/references/example repo",
    )
    args = sandbox.logged("args")
    volumes = [args[i + 1] for i, arg in enumerate(args) if arg == "-v"]
    assert volumes == [
        f"{first}:/references/example repo:ro",
        f"{second}:/references/docs,notes:ro",
    ]
    assert args[-3:] == [
        "agent", "ls", "/references/example repo"
    ]
    assert not (sandbox.log / "config-args").exists()


@pytest.mark.parametrize("value", ["", "missing", "/", "bad:path"])
def test_invalid_read_only_directory(sandbox, value):
    if value == "bad:path":
        (sandbox.repo / value).mkdir()
    sandbox.run(f"--mount-ro={value}", retcode=2)
    assert not (sandbox.log / "args").exists()


def test_read_only_directory_name_collision(sandbox):
    first = sandbox.repo / "a/example"
    second = sandbox.repo / "b/example"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    _, _, stderr = sandbox.run(
        "--mount-ro", str(first), "--mount-ro", str(second), retcode=2
    )
    assert "gleicher Ordnername bei --mount-ro: 'example'" in stderr
    assert not (sandbox.log / "args").exists()


def test_read_only_symlink_with_named_mount(sandbox):
    source = sandbox.repo.parent / "reference"
    source.mkdir()
    (sandbox.repo / "alias").symlink_to(
        source, target_is_directory=True
    )
    sandbox.run("-m", "devkit", "--mount-ro", "alias")
    args = sandbox.logged("args")
    assert f"{source}:/references/reference:ro" in args
    assert mount_file(sandbox, "devkit") in compose_files(args)
    assert args[-2:] == ["agent", "bash"]


@pytest.mark.parametrize("command", ["build", "mounts", "reset"])
def test_read_only_mount_only_for_shell_and_run(sandbox, command):
    _, _, stderr = sandbox.run("--mount-ro", ".", command, retcode=2)
    assert "--mount-ro gilt nur für shell und run" in stderr
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
    assert compose_files(args)[:3] == [
        str(sandbox.repo / "compose.yaml"),
        mount_file(sandbox, "devkit"),
        mount_file(sandbox, "mdman"),
    ]
    assert compose_files(args)[3:] == overlay_files(sandbox, args)
    assert args[-2:] == ["agent", "true"]


def test_unique_prefix_selects_mount(sandbox):
    sandbox.run("-m", "mdman-ai,lebens", "run", "true")
    assert compose_files(sandbox.logged("args"))[1:3] == [
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


@pytest.mark.parametrize(
    "config, setup, retcode",
    [
        ("lint:\n    max-chars:\n        notes: 600\n", "absent", 1),
        ("lint:\n    max-chars:\n        notes: 600\n", "unbuilt", 1),
        ("lint:\n    max-chars:\n        notes: 600\n", "built", 0),
        ("lint.max-chars.notes: 600\n", "absent", 1),
        ("# lint.max-chars.notes: 600\n", "absent", 0),
        ("export.auto: false\n", "absent", 0),
    ],
)
def test_max_chars_requires_local_bd(sandbox, config, setup, retcode):
    (sandbox.repo / ".beads").mkdir()
    (sandbox.repo / ".beads/config.yaml").write_text(config)
    beads = sandbox.repo.parent / "beads"
    if setup != "absent":
        beads.mkdir()
    if setup == "built":
        sandbox.add_executable(beads / ".build/linux/bd", "exit 0")
    _, _, stderr = sandbox.run("run", "true", retcode=retcode)
    if retcode:
        assert "uses lint.max-chars" in stderr
        assert not (sandbox.log / "args").exists()
    else:
        assert sandbox.logged("args")[-1] == "true"


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
    assert args[:5] == [
        "buildx",
        "build",
        "--load",
        "--build-arg",
        "FROM=venv",
    ]


def test_build_falls_back_to_system_python(sandbox):
    (sandbox.repo / ".venv/bin/python").unlink()
    fake_python(sandbox, sandbox.bin / "python3", "FROM=system")
    sandbox.run("build")
    args = sandbox.logged("args")
    assert args[:5] == [
        "buildx",
        "build",
        "--load",
        "--build-arg",
        "FROM=system",
    ]
    assert args[-3:-1] == [
        "-f",
        sandbox.logged("context")[0] + "/docker/agent/Dockerfile",
    ]
    assert sandbox.logged("files") == [
        "./docker/agent/Dockerfile",
        "./project/pyproject.toml",
        "./project/src/ki_dev/__init__.py",
        "./project/src/ki_dev/agent_dev_volumes.py",
        "./project/src/ki_dev/agent_repo_contract.py",
    ]
    assert not Path(sandbox.logged("context")[0]).exists()


def test_build_stops_when_versions_fail(sandbox):
    sandbox.add_executable(sandbox.bin / "python3", "exit 1")
    sandbox.run("build", retcode=1)
    assert not (sandbox.log / "args").exists()


def contract_document(name, deps):
    return json.dumps(
        {
            "services": {
                "agent": {
                    "volumes": [
                        {
                            "type": "bind",
                            "source": f"/src/{name}",
                            "target": f"/{name}",
                        }
                    ]
                }
            },
            "x-ki-dev": {"repo": f"/{name}", "deps": deps},
        }
    )


def test_invalid_contract_stops_before_docker(sandbox):
    (sandbox.log / "mdman.json").write_text(
        contract_document(
            "mdman",
            [{"manager": "pnpm", "inputs": ["x"], "install": "y"}],
        )
    )
    _, _, stderr = sandbox.run(
        "-m", "devkit,mdman", "run", "true", retcode=2
    )
    assert (
        "agent-container: mdman.yaml: x-ki-dev.deps.0.manager: "
        "unbekannter Wert"
    ) in stderr
    assert not (sandbox.log / "args").exists()


def test_contracts_read_with_project_directory(sandbox):
    sandbox.run("-m", "devkit,mdman", "run", "true")
    config_args = sandbox.logged("config-args")
    assert config_args.count("config") == 2
    assert config_args[:4] == [
        "compose",
        "-p",
        "ki-dev-contract",
        "--project-directory",
    ]
    assert config_args[4] == str(sandbox.repo)
    assert sandbox.logged("args")[-2:] == ["agent", "true"]


def test_no_contract_check_without_mounts(sandbox):
    sandbox.run("run", "true")
    assert not (sandbox.log / "config-args").exists()


def lebens_with_npm(sandbox):
    repo = sandbox.repo.parent / "lebens-src"
    repo.mkdir()
    (repo / "package.json").write_text("{}")
    document = json.loads(
        contract_document(
            "lebenslauf-web-vorlage",
            [
                {
                    "manager": "npm",
                    "inputs": ["package.json"],
                    "install": "node_modules",
                }
            ],
        )
    )
    document["services"]["agent"]["volumes"][0]["source"] = str(repo)
    (sandbox.log / "lebenslauf-web-vorlage.json").write_text(
        json.dumps(document)
    )


@pytest.mark.parametrize(
    ("options", "mode_file", "node_modules"),
    [
        ([], None, "volume"),
        (["--fresh"], "compose.fresh.yaml", "tmpfs"),
    ],
)
def test_mode_selects_compose_files(
    sandbox, options, mode_file, node_modules
):
    lebens_with_npm(sandbox)
    sandbox.run(*options, "-m", "lebens", "run", "true")
    args = sandbox.logged("args")
    files = compose_files(args)
    fresh = str(sandbox.repo / "compose.fresh.yaml")
    assert (fresh in files) == (mode_file is not None)
    [overlay] = overlay_files(sandbox, args)
    agent = json.loads(Path(overlay).read_text())["services"]["agent"]
    if node_modules == "volume":
        assert agent["volumes"][0]["target"] == (
            "/lebenslauf-web-vorlage/node_modules"
        )
    else:
        assert agent["tmpfs"][0].startswith(
            "/lebenslauf-web-vorlage/node_modules:"
        )
        assert files.index(overlay) < files.index(fresh)


def test_caches_are_created_and_exported(sandbox):
    sandbox.run("run", "true")
    cache = sandbox.cache / "agent-container"
    assert sandbox.logged("cache") == [str(cache)]
    assert sorted(path.name for path in cache.iterdir()) == [
        "go-build",
        "go-mod",
        "npm",
        "pip",
    ]


def test_cache_dir_defaults_to_home_cache(sandbox):
    sandbox.run("run", "true", env={"XDG_CACHE_HOME": ""})
    assert sandbox.logged("cache") == [
        str(sandbox.auth / ".cache/agent-container")
    ]


def test_stale_overlays_are_removed(sandbox):
    overlay_dir = sandbox.cache / "agent-container/compose"
    overlay_dir.mkdir(parents=True)
    stale = overlay_dir / "deps-999999.json"
    live = overlay_dir / f"deps-{os.getpid()}.json"
    for overlay in (stale, live):
        overlay.write_text("{}")
    sandbox.run("-m", "devkit", "run", "true")
    assert not stale.exists()
    assert live.exists()
    assert len(list(overlay_dir.iterdir())) == 2


@pytest.mark.parametrize("command", ["build", "mounts", "reset"])
def test_fresh_only_for_shell_and_run(sandbox, command):
    _, _, stderr = sandbox.run("--fresh", command, retcode=2)
    assert "--fresh applies only to shell and run" in stderr
    assert not (sandbox.log / "volume-calls").exists()


def volume_key(sandbox):
    pipeline = local["printf"]["%s", str(sandbox.repo)] | local["cksum"]
    with local.cwd(sandbox.repo):
        _, stdout, _ = pipeline.run(retcode=0, timeout=10)
    return stdout.split()[0]


def test_reset_removes_dev_volumes_of_checkout(sandbox):
    key = volume_key(sandbox)
    (sandbox.log / "volumes").write_text(
        f"ki-dev-agent-{key}-home\nki-dev-agent-{key}-venv\n"
        "ki-dev-agent-1-home\nki-dev-repo-mdman-node_modules\n"
        "ki-dev-repo-devkit-node_modules\n"
    )
    (sandbox.log / "volumes-ki-dev.repo=mdman").write_text(
        "ki-dev-repo-mdman-node_modules\n"
    )
    sandbox.run("-m", "mdman", "reset")
    assert sandbox.logged("volume-calls")[-1] == (
        f"volume rm ki-dev-agent-{key}-home ki-dev-agent-{key}-venv "
        "ki-dev-repo-mdman-node_modules"
    )
    assert not (sandbox.log / "args").exists()


def test_reset_skips_missing_volumes(sandbox):
    _, stdout, _ = sandbox.run("reset")
    assert stdout == "No dev volumes to remove.\n"
    assert sandbox.logged("volume-calls") == ["volume ls -q"]


def test_reset_reports_volume_in_use(sandbox):
    key = volume_key(sandbox)
    (sandbox.log / "volumes").write_text(f"ki-dev-agent-{key}-home\n")
    (sandbox.log / "rm-exit").write_text("1")
    _, _, stderr = sandbox.run("reset", retcode=1)
    assert "Stop running agent containers" in stderr


def run_git(cwd, *args):
    with local.cwd(cwd):
        local["git"].run(args=list(args), retcode=0, timeout=10)


@pytest.mark.parametrize("git", ["dir", "worktree", "none"])
def test_beads_build_is_git_excluded(sandbox, git):
    beads = sandbox.repo.parent / "beads"
    beads.mkdir()
    if git == "dir":
        run_git(beads.parent, "init", "-q", str(beads))
        exclude = beads / ".git/info/exclude"
    elif git == "worktree":
        main = sandbox.repo.parent / "beads-main"
        run_git(main.parent, "init", "-q", str(main))
        run_git(
            main,
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "x",
        )
        beads.rmdir()
        run_git(main, "worktree", "add", "-q", str(beads))
        exclude = main / ".git/info/exclude"
    for _ in range(2):
        sandbox.run("run", "true")
    if git == "none":
        assert not (beads / ".git").exists()
    else:
        assert exclude.read_text().splitlines().count(".build/") == 1


def test_beads_path_extends_image_path():
    dockerfile = (ROOT / "docker/agent/Dockerfile").read_text()
    image_path = re.search(r"\bPATH=(\S+)", dockerfile).group(1)
    beads = (ROOT / "compose.beads.yaml").read_text()
    beads_path = re.search(r"^\s+PATH: (\S+)$", beads, re.M).group(1)
    entries = image_path.split(":")
    assert entries[0] == "/opt/agent-bin"
    assert beads_path.split(":") == [
        entries[0],
        "/beads/.build/linux",
        *entries[1:],
    ]


@pytest.mark.parametrize(
    "args", [[], ["shell"], ["shell", "-lc", "pwd"]]
)
def test_fresh_shell_is_default(sandbox, args):
    sandbox.run("--fresh", *args)
    logged = sandbox.logged("args")
    assert str(sandbox.repo / "compose.fresh.yaml") in compose_files(
        logged
    )
    assert logged[logged.index("agent") + 1] == "bash"


class _MarkConfig:
    def __init__(self, markexpr):
        self.markexpr = markexpr

    def getoption(self, name):
        assert name == "markexpr"
        return self.markexpr


@pytest.mark.parametrize(
    "markexpr, requested",
    [
        ("docker", True),
        ("docker or not docker", True),
        ("slow", True),
        ("", False),
        (None, False),
    ],
)
def test_docker_fails_only_when_requested(markexpr, requested):
    assert docker_requested(_MarkConfig(markexpr)) is requested
