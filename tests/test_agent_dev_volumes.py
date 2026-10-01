"""Compose-Einbindung der Abhängigkeitsverzeichnisse je Modus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ki_dev import agent_dev_volumes
from ki_dev.agent_dev_volumes import (
    SEED_SLOTS,
    dev_overlay,
    fresh_overlay,
    volume_name,
)
from ki_dev.agent_repo_contract import (
    ComposeError,
    ContractError,
    Dependency,
    RepoContract,
)


def contract(name, *deps):
    return RepoContract(name, f"/{name}", f"/src/{name}", list(deps))


NPM = Dependency("npm", ["package.json"], "node_modules")
COMPOSER = Dependency("composer", ["composer.json"], "vendor")


def test_dev_overlay_labels_volume_and_seeds_owner():
    overlay = dev_overlay(
        [
            contract("lebens", NPM, COMPOSER),
            contract("site", Dependency("npm", ["a"], "web/node_modules")),
        ]
    )
    assert overlay == {
        "services": {
            "agent": {
                "volumes": [
                    {
                        "type": "volume",
                        "source": "deps-0",
                        "target": "/lebens/node_modules",
                    },
                    {
                        "type": "volume",
                        "source": "deps-0",
                        "target": "/opt/agent-volume-seed/0",
                    },
                    {
                        "type": "volume",
                        "source": "deps-1",
                        "target": "/site/web/node_modules",
                    },
                    {
                        "type": "volume",
                        "source": "deps-1",
                        "target": "/opt/agent-volume-seed/1",
                    },
                ]
            }
        },
        "volumes": {
            "deps-0": {
                "name": "ki-dev-repo-lebens-node_modules",
                "labels": {"ki-dev.repo": "lebens"},
            },
            "deps-1": {
                "name": "ki-dev-repo-site-web-node_modules",
                "labels": {"ki-dev.repo": "site"},
            },
        },
    }


def test_without_npm_overlay_is_empty():
    assert dev_overlay([contract("php", COMPOSER)]) == {
        "services": {"agent": {"volumes": []}},
        "volumes": {},
    }
    assert fresh_overlay([], 1, 2) == {"services": {"agent": {"tmpfs": []}}}


def test_dev_overlay_limited_to_seed_slots():
    dev_overlay([contract(f"r{n}", NPM) for n in range(SEED_SLOTS)])
    with pytest.raises(ContractError) as error:
        dev_overlay([contract(f"r{n}", NPM) for n in range(SEED_SLOTS + 1)])
    assert str(error.value) == (
        f"höchstens {SEED_SLOTS} Abhängigkeitsverzeichnisse je Lauf, "
        f"gewählt: {SEED_SLOTS + 1}"
    )


def test_seed_slots_match_dockerfile():
    dockerfile = (
        Path(__file__).resolve().parents[1] / "docker/agent/Dockerfile"
    ).read_text()
    slots = " ".join(map(str, range(SEED_SLOTS)))
    assert f"for slot in {slots}; do" in dockerfile


def test_fresh_overlay_uses_owned_tmpfs():
    assert fresh_overlay([contract("lebens", NPM, COMPOSER)], 501, 20) == {
        "services": {
            "agent": {
                "tmpfs": [
                    "/lebens/node_modules:"
                    "rw,exec,nosuid,nodev,uid=501,gid=20,mode=0755"
                ]
            }
        }
    }


def test_volume_name_keeps_docker_charset():
    assert volume_name("lebens", "a b/node_modules") == (
        "ki-dev-repo-lebens-a-b-node_modules"
    )


@pytest.mark.parametrize(
    ("error", "code"), [(None, 0), (ContractError, 2), (ComposeError, 1)]
)
def test_cli_prints_overlay_or_fails(monkeypatch, capsys, tmp_path, error, code):
    def read(mount_files, project_directory):
        assert project_directory == tmp_path
        if error is not None:
            raise error("lebens.yaml: kaputt")
        return [contract("lebens", NPM)]

    monkeypatch.setattr(agent_dev_volumes, "read_contracts", read)
    result = agent_dev_volumes.main(
        [
            "--mode",
            "test",
            "--uid",
            "501",
            "--gid",
            "20",
            "--project-directory",
            str(tmp_path),
            "lebens.yaml",
        ]
    )
    assert result == code
    captured = capsys.readouterr()
    if error is None:
        assert json.loads(captured.out)["services"]["agent"]["tmpfs"]
    else:
        assert captured.err == "agent-container: lebens.yaml: kaputt\n"
        assert captured.out == ""
