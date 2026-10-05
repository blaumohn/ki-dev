"""Repo-Vertrag x-ki-dev in den Mount-Dateien des Agent-Containers.

Eine Mount-Datei darf neben ihren Einbindungen ein Feld x-ki-dev tragen:
welches eingebundene Repo welche Paketverwalter, Eingabedateien und
Installationsverzeichnisse hat. Compose ignoriert x-Felder; dieser
Helfer prüft sie und gibt die normalisierten Verträge als JSON aus. Das
Modul importiert keine anderen ki_dev-Module, damit
scripts/agent-container es auch mit einem Host-Python ohne Projekt-venv
aufrufen kann.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from plumbum import local
from plumbum.commands.processes import (
    CommandNotFound,
    ProcessExecutionError,
    ProcessTimedOut,
)

MANAGERS = ("npm", "composer")
_RELATIVE_PATH = {"type": "string", "pattern": r"^[^/\s]\S*$"}
_VALIDATOR = Draft202012Validator(
    {
        "type": "object",
        "properties": {
            "repo": {"type": "string", "pattern": r"^/\S+$"},
            "deps": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "manager": {"enum": list(MANAGERS)},
                        "inputs": {
                            "type": "array",
                            "minItems": 1,
                            "uniqueItems": True,
                            "items": _RELATIVE_PATH,
                        },
                        "install": _RELATIVE_PATH,
                    },
                    "required": ["manager", "inputs", "install"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["repo", "deps"],
        "additionalProperties": False,
    }
)
_REASONS = {
    "required": "Pflichtfeld fehlt",
    "additionalProperties": "unbekanntes Feld",
    "type": "falscher Typ",
    "enum": "unbekannter Wert",
    "minItems": "darf nicht leer sein",
    "uniqueItems": "doppelter Eintrag",
    "pattern": "ungültiger Pfad",
}
FIELD = "x-ki-dev"
COMPOSE_TIMEOUT = 30


class ContractError(ValueError):
    """Ungültiger Vertrag; die Meldung nennt den Feldpfad."""


class ComposeError(RuntimeError):
    """docker compose config ist nicht nutzbar (fehlt, Frist,
    Ausgabe)."""


@dataclass(frozen=True)
class Dependency:
    manager: str
    inputs: list[str]
    install: str


@dataclass(frozen=True)
class RepoContract:
    name: str
    repo: str
    source: str
    deps: list[Dependency]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m ki_dev.agent_repo_contract",
        description="Prüft x-ki-dev in Mount-Dateien und gibt die "
        "normalisierten Verträge als JSON aus.",
    )
    parser.add_argument(
        "--agent",
        action="store_true",
        help="Agent-Modus: höchstens ein Repo mit deps",
    )
    parser.add_argument("--project-directory", type=Path, required=True)
    parser.add_argument("mount_files", nargs="+", type=Path)
    arguments = parser.parse_args(argv)
    try:
        contracts = read_contracts(
            arguments.mount_files, arguments.project_directory
        )
        if arguments.agent:
            require_single_repo(contracts)
    except ContractError as exc:
        print(f"agent-container: {exc}", file=sys.stderr)
        return 2
    except ComposeError as exc:
        print(f"agent-container: {exc}", file=sys.stderr)
        return 1
    json.dump([asdict(contract) for contract in contracts], sys.stdout)
    print()
    return 0


def read_contracts(
    mount_files: list[Path], project_directory: Path
) -> list[RepoContract]:
    contracts = []
    for mount_file in mount_files:
        document = load_mount_file(mount_file, project_directory)
        contract = check_mount_document(document, mount_file.stem)
        if contract is not None:
            contracts.append(contract)
    return contracts


# Compose parses the YAML: the project needs no YAML library, and the
# contract sees the same syntax, interpolation and path normalization as
# the real run (relative sources against the ki-dev checkout).
def load_mount_file(mount_file: Path, project_directory: Path) -> dict:
    arguments = [
        "compose",
        "-p",
        "ki-dev-contract",
        "--project-directory",
        str(project_directory),
        "-f",
        str(mount_file),
        "config",
        "--no-consistency",
        "--format",
        "json",
    ]
    label = mount_file.name
    try:
        with local.cwd(project_directory):
            _, stdout, _ = local["docker"].run(
                args=arguments, retcode=0, timeout=COMPOSE_TIMEOUT
            )
    except CommandNotFound as exc:
        raise ComposeError("docker nicht gefunden") from exc
    except ProcessTimedOut as exc:
        raise ComposeError(
            f"{label}: docker compose config über {COMPOSE_TIMEOUT} s"
        ) from exc
    except ProcessExecutionError as exc:
        raise ContractError(
            f"{label}: Compose kann die Datei nicht lesen "
            f"(Exit {exc.retcode}); prüfen mit: "
            f"docker compose -f {mount_file} config"
        ) from exc
    try:
        document = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ComposeError(
            f"{label}: docker compose config lieferte kein JSON"
        ) from exc
    if not isinstance(document, dict):
        raise ComposeError(
            f"{label}: docker compose config lieferte kein Objekt"
        )
    return document


def check_mount_document(
    document: dict, name: str
) -> RepoContract | None:
    """Prüft x-ki-dev eines Compose-Dokuments; ohne das Feld None."""
    if FIELD not in document:
        return None
    label = f"{name}.yaml"
    value = document[FIELD]
    validate_contract(value, label)
    source = bind_source(document, value["repo"])
    if source is None:
        raise ContractError(
            f"{label}: {FIELD}.repo: ist kein target dieser Datei"
        )
    deps = check_deps(value["deps"], Path(source), f"{label}: {FIELD}")
    return RepoContract(name, value["repo"], source, deps)


def validate_contract(value: object, label: str) -> None:
    error = best_match(_VALIDATOR.iter_errors(value))
    if error is None:
        return
    parts = [FIELD, *map(str, error.absolute_path)]
    if error.validator == "required":
        missing = [
            key
            for key in error.validator_value
            if key not in error.instance
        ]
        parts.append(missing[0])
    elif error.validator == "additionalProperties":
        allowed = error.schema.get("properties", {})
        parts.append(sorted(set(error.instance) - set(allowed))[0])
    reason = _REASONS[error.validator]
    raise ContractError(f"{label}: {'.'.join(parts)}: {reason}")


def bind_source(document: dict, target: str) -> str | None:
    services = document.get("services") or {}
    agent = services.get("agent") or {}
    for volume in agent.get("volumes") or []:
        if (
            isinstance(volume, dict)
            and volume.get("type") == "bind"
            and volume.get("target") == target
        ):
            return volume.get("source")
    return None


def check_deps(
    deps: list[dict], source: Path, prefix: str
) -> list[Dependency]:
    """Pfade innerhalb von repo, install eindeutig, inputs vorhanden."""
    checked = []
    installs: set[str] = set()
    for index, dep in enumerate(deps):
        path = f"{prefix}.deps.{index}"
        install = inside_repo(dep["install"], f"{path}.install")
        if install in installs:
            raise ContractError(
                f"{path}.install: doppelter install-Pfad"
            )
        installs.add(install)
        inputs = [
            inside_repo(item, f"{path}.inputs.{position}")
            for position, item in enumerate(dep["inputs"])
        ]
        for position, item in enumerate(inputs):
            if not (source / item).is_file():
                raise ContractError(
                    f"{path}.inputs.{position}: Datei fehlt im Repo"
                )
        checked.append(Dependency(dep["manager"], inputs, install))
    return checked


def inside_repo(value: str, path: str) -> str:
    """Normalisiert einen relativen Pfad; ../ verlässt das Repo."""
    normalized = PurePosixPath(value)
    if ".." in normalized.parts or str(normalized) == ".":
        raise ContractError(f"{path}: liegt außerhalb von repo")
    return str(normalized)


def require_single_repo(contracts: list[RepoContract]) -> None:
    if len(contracts) > 1:
        names = ", ".join(contract.name for contract in contracts)
        raise ContractError(
            "Agent-Modus: höchstens ein Repo mit deps, "
            f"gewählt: {names}"
        )


if __name__ == "__main__":
    sys.exit(main())
