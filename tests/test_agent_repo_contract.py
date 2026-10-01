"""Repo-Vertrag x-ki-dev: Schema, benannte Prüfungen und CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from plumbum import local

from ki_dev import agent_repo_contract
from ki_dev.agent_repo_contract import (
    ComposeError,
    ContractError,
    Dependency,
    RepoContract,
    check_mount_document,
)


@pytest.fixture
def repo(tmp_path):
    source = tmp_path / "lebens"
    source.mkdir()
    for name in ("package.json", "package-lock.json", "composer.json"):
        (source / name).write_text("{}")
    return source


def document(repo, contract, target="/lebens"):
    return {
        "services": {
            "agent": {
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(repo),
                        "target": target,
                    },
                    {"type": "tmpfs", "target": "/lebens/var"},
                ]
            }
        },
        "x-ki-dev": contract,
    }


def npm(**changes):
    return {
        "manager": "npm",
        "inputs": ["package.json", "package-lock.json"],
        "install": "node_modules",
        **changes,
    }


def test_file_without_contract_is_valid():
    assert check_mount_document({"services": {}}, "devkit") is None


def test_empty_contract_is_not_missing(repo):
    with pytest.raises(ContractError) as error:
        check_mount_document(document(repo, None), "lebens")
    assert str(error.value) == "lebens.yaml: x-ki-dev: falscher Typ"


def test_contract_is_normalized(repo):
    contract = {
        "repo": "/lebens",
        "deps": [
            npm(install="./node_modules/"),
            {
                "manager": "composer",
                "inputs": ["./composer.json"],
                "install": "vendor",
            },
        ],
    }
    assert check_mount_document(document(repo, contract), "lebens") == (
        RepoContract(
            "lebens",
            "/lebens",
            str(repo),
            [
                Dependency(
                    "npm",
                    ["package.json", "package-lock.json"],
                    "node_modules",
                ),
                Dependency("composer", ["composer.json"], "vendor"),
            ],
        )
    )


@pytest.mark.parametrize(
    ("contract", "message"),
    [
        (7, "x-ki-dev: falscher Typ"),
        ({"deps": [npm()]}, "x-ki-dev.repo: Pflichtfeld fehlt"),
        ({"repo": "/lebens"}, "x-ki-dev.deps: Pflichtfeld fehlt"),
        (
            {"repo": "/lebens", "deps": [npm()], "extra": 1},
            "x-ki-dev.extra: unbekanntes Feld",
        ),
        (
            {"repo": "lebens", "deps": [npm()]},
            "x-ki-dev.repo: ungültiger Pfad",
        ),
        (
            {"repo": "/lebens", "deps": []},
            "x-ki-dev.deps: darf nicht leer sein",
        ),
        (
            {"repo": "/lebens", "deps": [npm(manager="pnpm")]},
            "x-ki-dev.deps.0.manager: unbekannter Wert",
        ),
        (
            {"repo": "/lebens", "deps": [npm(inputs=[])]},
            "x-ki-dev.deps.0.inputs: darf nicht leer sein",
        ),
        (
            {"repo": "/lebens", "deps": [npm(inputs=["a", "a"])]},
            "x-ki-dev.deps.0.inputs: doppelter Eintrag",
        ),
        (
            {
                "repo": "/lebens",
                "deps": [{"manager": "npm", "inputs": ["x"]}],
            },
            "x-ki-dev.deps.0.install: Pflichtfeld fehlt",
        ),
        (
            {"repo": "/lebens", "deps": [npm(install="/node_modules")]},
            "x-ki-dev.deps.0.install: ungültiger Pfad",
        ),
        (
            {
                "repo": "/lebens",
                "deps": [npm(install="../node_modules")],
            },
            "x-ki-dev.deps.0.install: liegt außerhalb von repo",
        ),
        (
            {"repo": "/lebens", "deps": [npm(install="a/../../b")]},
            "x-ki-dev.deps.0.install: liegt außerhalb von repo",
        ),
        (
            {"repo": "/lebens", "deps": [npm(install=".")]},
            "x-ki-dev.deps.0.install: liegt außerhalb von repo",
        ),
        (
            {
                "repo": "/lebens",
                "deps": [npm(inputs=["../package.json"])],
            },
            "x-ki-dev.deps.0.inputs.0: liegt außerhalb von repo",
        ),
        (
            {
                "repo": "/lebens",
                "deps": [npm(inputs=["package.json", "yarn.lock"])],
            },
            "x-ki-dev.deps.0.inputs.1: Datei fehlt im Repo",
        ),
        (
            {
                "repo": "/lebens",
                "deps": [
                    npm(),
                    npm(
                        manager="composer",
                        inputs=["composer.json"],
                        install="node_modules/",
                    ),
                ],
            },
            "x-ki-dev.deps.1.install: doppelter install-Pfad",
        ),
        (
            {"repo": "/lebens/var", "deps": [npm()]},
            "x-ki-dev.repo: ist kein target dieser Datei",
        ),
    ],
)
def test_invalid_contract_names_field(repo, contract, message):
    with pytest.raises(ContractError) as error:
        check_mount_document(document(repo, contract), "lebens")
    assert str(error.value) == f"lebens.yaml: {message}"


def test_error_does_not_echo_raw_values(repo):
    contract = {"repo": "/lebens", "deps": [npm(manager="geheim-123")]}
    with pytest.raises(ContractError) as error:
        check_mount_document(document(repo, contract), "lebens")
    assert "geheim-123" not in str(error.value)


@pytest.fixture
def mount_documents(monkeypatch, tmp_path, repo):
    documents = {}

    def load(mount_file, project_directory):
        assert project_directory == tmp_path
        return documents[mount_file.stem]

    monkeypatch.setattr(agent_repo_contract, "load_mount_file", load)
    return documents


def run_main(tmp_path, *args):
    return agent_repo_contract.main(
        ["--project-directory", str(tmp_path), *args]
    )


def test_cli_prints_contracts(tmp_path, repo, mount_documents, capsys):
    mount_documents["lebens"] = document(
        repo, {"repo": "/lebens", "deps": [npm()]}
    )
    mount_documents["devkit"] = {"services": {}}
    assert run_main(tmp_path, "lebens.yaml", "devkit.yaml") == 0
    assert json.loads(capsys.readouterr().out) == [
        {
            "name": "lebens",
            "repo": "/lebens",
            "source": str(repo),
            "deps": [
                {
                    "manager": "npm",
                    "inputs": ["package.json", "package-lock.json"],
                    "install": "node_modules",
                }
            ],
        }
    ]


@pytest.mark.parametrize(("agent", "code"), [(False, 0), (True, 2)])
def test_agent_mode_allows_one_repo_with_deps(
    tmp_path, repo, mount_documents, capsys, agent, code
):
    for name in ("lebens", "keylita"):
        mount_documents[name] = document(
            repo,
            {"repo": f"/{name}", "deps": [npm()]},
            target=f"/{name}",
        )
    mount_documents["devkit"] = {"services": {}}
    args = ["--agent"] if agent else []
    files = ["lebens.yaml", "devkit.yaml", "keylita.yaml"]
    assert run_main(tmp_path, *args, *files) == code
    if agent:
        assert capsys.readouterr().err == (
            "agent-container: Agent-Modus: höchstens ein Repo mit deps, "
            "gewählt: lebens, keylita\n"
        )


def test_agent_mode_accepts_single_repo(
    tmp_path, repo, mount_documents
):
    mount_documents["lebens"] = document(
        repo, {"repo": "/lebens", "deps": [npm()]}
    )
    mount_documents["devkit"] = {"services": {}}
    assert (
        run_main(tmp_path, "--agent", "lebens.yaml", "devkit.yaml") == 0
    )


def test_template_shows_contract_commented():
    template = (
        Path(__file__).resolve().parents[1]
        / "docker/agent/mount.example.yaml"
    ).read_text()
    assert "# x-ki-dev:" in template
    assert "\nx-ki-dev:" not in template


@pytest.fixture
def fake_docker(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    def install(body):
        docker = bin_dir / "docker"
        docker.write_text(f"#!/bin/sh\n{body}\n")
        docker.chmod(0o755)

    with local.env(PATH=f"{bin_dir}:/usr/bin:/bin"):
        yield install


def test_load_reads_compose_json(tmp_path, fake_docker):
    fake_docker('echo "$@" >&2; echo \'{"x-ki-dev": 7}\'')
    mount_file = tmp_path / "lebens.yaml"
    assert agent_repo_contract.load_mount_file(mount_file, tmp_path) == {
        "x-ki-dev": 7
    }


@pytest.mark.parametrize(
    ("body", "error", "message"),
    [
        (
            "exit 15",
            ContractError,
            "lebens.yaml: Compose kann die Datei nicht lesen (Exit 15)",
        ),
        ("echo kaputt", ComposeError, "lebens.yaml: docker compose config "
         "lieferte kein JSON"),
        ("echo '[]'", ComposeError, "lebens.yaml: docker compose config "
         "lieferte kein Objekt"),
        (None, ComposeError, "docker nicht gefunden"),
    ],
)
def test_load_reports_compose_failures(
    tmp_path, fake_docker, body, error, message
):
    if body is not None:
        fake_docker(body)
    with pytest.raises(error) as raised:
        agent_repo_contract.load_mount_file(
            tmp_path / "lebens.yaml", tmp_path
        )
    assert str(raised.value).startswith(message)


def test_load_passes_project_directory(tmp_path, fake_docker):
    log = tmp_path / "args"
    fake_docker(f"printf '%s\\n' \"$@\" > {log}; echo '{{}}'")
    agent_repo_contract.load_mount_file(tmp_path / "m.yaml", tmp_path)
    assert log.read_text().splitlines() == [
        "compose", "-p", "ki-dev-contract",
        "--project-directory", str(tmp_path),
        "-f", str(tmp_path / "m.yaml"),
        "config", "--no-consistency", "--format", "json",
    ]


@pytest.mark.parametrize(("code", "error"), [(2, ContractError), (1, ComposeError)])
def test_cli_exit_codes(tmp_path, monkeypatch, capsys, code, error):
    def fail(mount_file, project_directory):
        raise error("lebens.yaml: kaputt")

    monkeypatch.setattr(agent_repo_contract, "load_mount_file", fail)
    assert run_main(tmp_path, "lebens.yaml") == code
    assert capsys.readouterr().err == "agent-container: lebens.yaml: kaputt\n"
