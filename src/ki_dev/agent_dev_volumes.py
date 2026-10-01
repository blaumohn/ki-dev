"""Compose-Einbindung der Abhängigkeitsverzeichnisse aus x-ki-dev.

Für jedes npm-Installationsverzeichnis eines Repo-Vertrags entsteht eine
Compose-Datei (JSON ist gültiges YAML), die scripts/agent-container nach
compose.yaml und den Mount-Dateien anwendet:

- dev: ein Named Volume je Repo und Verzeichnis mit Label ki-dev.repo=NAME,
  Linux-eigen und über Läufe erhalten; der Mac-Stand im Checkout bleibt
  unberührt. Jedes Volume hängt zusätzlich an einem agent-eigenen
  Seed-Platz des Images, damit Docker es beim Anlegen nicht root überlässt.
- test (--fresh): ein tmpfs mit dem Container-Benutzer als Eigentümer, das
  mit dem Container verschwindet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from ki_dev.agent_repo_contract import (
    ComposeError,
    ContractError,
    RepoContract,
    read_contracts,
)

VOLUME_MANAGERS = ("npm",)
SEED_ROOT = "/opt/agent-volume-seed"
# Matches the slots created in docker/agent/Dockerfile.
SEED_SLOTS = 8
REPO_LABEL = "ki-dev.repo"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ki_dev.agent_dev_volumes",
        description="Prüft x-ki-dev in Mount-Dateien und gibt die "
        "Compose-Einbindung der Abhängigkeitsverzeichnisse aus.",
    )
    parser.add_argument("--mode", choices=("dev", "test"), required=True)
    parser.add_argument("--uid", type=int, required=True)
    parser.add_argument("--gid", type=int, required=True)
    parser.add_argument("--project-directory", type=Path, required=True)
    parser.add_argument("mount_files", nargs="+", type=Path)
    arguments = parser.parse_args(argv)
    try:
        contracts = read_contracts(
            arguments.mount_files, arguments.project_directory
        )
        if arguments.mode == "dev":
            overlay = dev_overlay(contracts)
        else:
            overlay = fresh_overlay(
                contracts, arguments.uid, arguments.gid
            )
    except ContractError as exc:
        print(f"agent-container: {exc}", file=sys.stderr)
        return 2
    except ComposeError as exc:
        print(f"agent-container: {exc}", file=sys.stderr)
        return 1
    json.dump(overlay, sys.stdout, indent=2)
    print()
    return 0


def install_targets(
    contracts: list[RepoContract],
) -> list[tuple[str, str, str]]:
    """(Repo-Name, install, Container-Pfad) je Volume-Verzeichnis."""
    return [
        (contract.name, dep.install, f"{contract.repo}/{dep.install}")
        for contract in contracts
        for dep in contract.deps
        if dep.manager in VOLUME_MANAGERS
    ]


def dev_overlay(contracts: list[RepoContract]) -> dict:
    targets = install_targets(contracts)
    if len(targets) > SEED_SLOTS:
        raise ContractError(
            f"höchstens {SEED_SLOTS} Abhängigkeitsverzeichnisse je Lauf, "
            f"gewählt: {len(targets)}"
        )
    mounts = []
    volumes = {}
    for slot, (name, install, target) in enumerate(targets):
        key = f"deps-{slot}"
        mounts.append({"type": "volume", "source": key, "target": target})
        mounts.append(
            {
                "type": "volume",
                "source": key,
                "target": f"{SEED_ROOT}/{slot}",
            }
        )
        volumes[key] = {
            "name": volume_name(name, install),
            "labels": {REPO_LABEL: name},
        }
    return {"services": {"agent": {"volumes": mounts}}, "volumes": volumes}


def volume_name(name: str, install: str) -> str:
    """Lesbarer Name; der Hash trennt Pfade mit gleichem Slug."""
    slug = re.sub(r"[^A-Za-z0-9_.-]", "-", install)
    digest = hashlib.sha256(f"{name}\0{install}".encode()).hexdigest()
    return f"ki-dev-repo-{name}-{slug}-{digest[:12]}"


def fresh_overlay(contracts: list[RepoContract], uid: int, gid: int) -> dict:
    options = f"rw,exec,nosuid,nodev,uid={uid},gid={gid},mode=0755"
    tmpfs = [
        f"{target}:{options}" for _, _, target in install_targets(contracts)
    ]
    return {"services": {"agent": {"tmpfs": tmpfs}}}


if __name__ == "__main__":
    sys.exit(main())
