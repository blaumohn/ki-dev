"""Echter Docker-Lauf: Dev-Modus, --fresh, geteilte Caches und reset.

Läuft gegen eine Kopie des Checkouts; deren Pfad ergibt einen eigenen
Volume-Schlüssel, sodass reset die echten Dev-Volumes nicht berührt. Die
Kopie liegt unter .local/ im Checkout: Colima gibt nur das Home an die
VM frei, nicht /tmp.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from plumbum import local

from ki_dev.agent_dev_volumes import volume_name

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ki-dev-agent:local"
pytestmark = pytest.mark.docker


def docker_ready():
    if shutil.which("docker") is None:
        return False
    with local.cwd(ROOT):
        code, _, _ = local["docker"].run(
            args=["image", "inspect", IMAGE], retcode=None, timeout=30
        )
    home = Path.home()
    return code == 0 and (home / ".claude").is_dir() and (
        home / ".codex"
    ).is_dir() and (home / ".gemini").is_dir()


@pytest.fixture
def shared_tmp():
    base = ROOT / ".local/pytest-docker"
    base.mkdir(parents=True, exist_ok=True)
    path = Path(tempfile.mkdtemp(dir=base))
    yield path
    shutil.rmtree(path)


def docker_requested(config):
    """Mit ``-m`` ausgewählt und trotzdem ausgeführt: fehlende
    Voraussetzung ist ein Fehler; ohne Markerausdruck ein Skip."""
    return bool(config.getoption("markexpr"))


@pytest.fixture
def checkout(shared_tmp, request):
    if not docker_ready():
        # Geprüft wird ein vorhandenes Image, nicht dessen Bau.
        reason = (
            f"Docker, Image {IMAGE} oder CLI-Anmeldung fehlt"
            " (Image vorher mit ./scripts/agent-container build bauen)"
        )
        if docker_requested(request.config):
            pytest.fail(reason)
        pytest.skip(reason)
    tmp_path = shared_tmp
    repo = tmp_path / "ki-dev"
    repo.mkdir()
    for name in (
        "compose.yaml",
        "compose.fresh.yaml",
        "compose.beads.yaml",
    ):
        shutil.copy(ROOT / name, repo)
    shutil.copytree(ROOT / "scripts", repo / "scripts")
    shutil.copytree(ROOT / "src/ki_dev", repo / "src/ki_dev")
    shutil.copytree(
        ROOT / "docker/agent-settings", repo / "docker/agent-settings"
    )
    python = repo / ".venv/bin/python"
    python.parent.mkdir(parents=True)
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
    python.chmod(0o755)
    lebens = tmp_path / "lebens"
    lebens.mkdir()
    (lebens / "package.json").write_text("{}")
    # Unique per run: repo volumes are global per name (label
    # ki-dev.repo), so reset in the teardown must not hit another
    # checkout's volume.
    name = "lebens-" + re.sub(r"[^a-z0-9]", "", tmp_path.name.lower())
    mounts = tmp_path / "config/ki-dev/agent-container/mounts"
    mounts.mkdir(parents=True)
    (mounts / f"{name}.yaml").write_text(
        "x-ki-dev:\n"
        "  repo: /lebens\n"
        "  deps:\n"
        "    - {manager: npm, inputs: [package.json], install: "
        "node_modules}\n"
        "services:\n"
        "  agent:\n"
        "    volumes:\n"
        f"      - {{type: bind, source: {lebens}, target: /lebens}}\n"
    )
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("KI_DEV_")
    }
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    script = local[str(repo / "scripts/agent-container")]

    def run(*args, retcode=0):
        with local.env(**env), local.cwd(repo):
            return script.run(
                args=list(args), retcode=retcode, timeout=300
            )

    yield run, name, tmp_path / "cache/agent-container"
    run("-m", name, "reset")
    project = f"ki-dev-agent-{volume_key(repo)}"
    # Compose run leaves the project network behind; absent is fine.
    with local.cwd(ROOT):
        local["docker"].run(
            args=["network", "rm", f"{project}_default"],
            retcode=(0, 1),
            timeout=30,
        )


def volume_key(repo):
    pipeline = local["printf"]["%s", str(repo)] | local["cksum"]
    with local.cwd(ROOT):
        _, stdout, _ = pipeline.run(retcode=0, timeout=10)
    return stdout.split()[0]


def volumes():
    with local.cwd(ROOT):
        _, stdout, _ = local["docker"].run(
            args=["volume", "ls", "-q"], retcode=0, timeout=30
        )
    return set(stdout.split())


FRESH_CHECKS = """
test ! -e ~/dev-marker && echo home-frisch
test ! -e /workspace/.venv/dev-marker \
  && /workspace/.venv/bin/python -c 1 && echo venv-frisch
test -z "$(ls -A ~/.cache/go-build)" && echo go-build-leer
test -z "$(ls -A /lebens/node_modules)" \
  && touch /lebens/node_modules/x && echo node_modules-frisch
grep -qs ' /lebens/node_modules tmpfs ' \
  /proc/mounts && echo node_modules-tmpfs
test "$(cat ~/.npm/shared)" = treffer && echo cache-treffer
touch ~/.cache/go-build/aus-fresh ~/fresh-marker
"""


def test_dev_persists_fresh_is_temporary(checkout):
    run, name, cache = checkout
    before = volumes()
    run(
        "-m",
        name,
        "run",
        "sh",
        "-c",
        "touch ~/dev-marker /workspace/.venv/dev-marker"
        " /lebens/node_modules/dev && echo treffer > ~/.npm/shared",
    )
    (cache / "go-build/host-marker").write_text("")
    after_dev = volumes()
    created = after_dev - before
    assert any(name.endswith("-home") for name in created)
    assert volume_name(name, "node_modules") in created

    _, stdout, _ = run(
        "--fresh", "-m", name, "run", "sh", "-c", FRESH_CHECKS
    )
    assert stdout.split() == [
        "home-frisch",
        "venv-frisch",
        "go-build-leer",
        "node_modules-frisch",
        "node_modules-tmpfs",
        "cache-treffer",
    ]
    assert volumes() == after_dev
    assert [path.name for path in (cache / "go-build").iterdir()] == [
        "host-marker"
    ]

    _, stdout, _ = run(
        "-m",
        name,
        "run",
        "sh",
        "-c",
        "test -e ~/dev-marker && test -e /lebens/node_modules/dev"
        " && test ! -e ~/fresh-marker && echo dev-erhalten",
    )
    assert stdout.split() == ["dev-erhalten"]

    run("-m", name, "reset")
    assert not created & volumes()
