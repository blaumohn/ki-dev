from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parents[1]
PERSONAS = ("techlead", "entwickler", "pruefer")
SEARCH_HEADER = "Konfiguration (der erste vorhandene Pfad gilt):"


def _run(repo, cwd, args, extra_env=None, check=True):
    env = os.environ.copy()
    env["XDG_CONFIG_HOME"] = str(Path(cwd) / "xdg-config")
    env.update(extra_env or {})
    return subprocess.run(
        [str(repo / "scripts/readme-walkthrough"), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=check,
        timeout=10,
    )


def _config_file(cwd):
    return Path(cwd) / "xdg-config/ki-dev/readme-walkthrough"


def _write_config(cwd, value):
    path = _config_file(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Ausgabeordner für readme-walkthrough\nausgabe = {value}\n"
    )


def _prepare(repo, cwd, base=None, extra_env=None):
    if base is not None:
        _write_config(cwd, base)
    result = _run(repo, cwd, ["prepare"], extra_env)
    return Path(result.stdout.strip())


def test_prepare_repository_from_another_directory(tmp_path):
    base = tmp_path / "persona files"
    readme = (REPO / "README.md").read_bytes()

    target = _prepare(REPO, tmp_path, base)
    assert target.parent == base
    assert re.fullmatch(r"[0-9a-f]+-\d{6}T\d{4}", target.name)

    tracked = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    roots = sorted(
        {path.split("/")[0] for path in tracked.stdout.splitlines()}
    )
    for persona in PERSONAS:
        directory = target / persona
        assert (directory / "README.md").read_bytes() == readme
        assert (
            directory / "root.txt"
        ).read_text().splitlines() == roots
        handoff = (directory / "uebergabe.txt").read_text()
        assert not re.search(r"@[^@\n]+@", handoff)
        assert "ja/nein" in handoff
        assert "Ändere nichts." in handoff
        assert "in drei Sätzen" in handoff
        assert "mit beiden\n   Lesarten" in handoff
        assert "Fährte verloren" in handoff
        assert "kein Gesamturteil" in handoff
    for relative in (
        "tests/machine/test_reachability.py",
        "docs/ausfuehrer.de.md",
        "src/ki_dev/flow/implement.toml",
    ):
        flat = relative.replace("/", "__")
        assert (target / "pruefer" / flat).read_bytes() == (
            REPO / relative
        ).read_bytes()
        assert (
            f"{flat}  {relative}\n"
            in (target / "pruefer/dateien.txt").read_text()
        )
    assert (
        "Begründe mit Testcode."
        in (target / "pruefer/uebergabe.txt").read_text()
    )
    assert (REPO / "README.md").read_bytes() == readme


@pytest.fixture
def example_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    for name in (
        "readme-walkthrough",
        "readme-walkthrough-uebergabe.txt",
    ):
        shutil.copy2(REPO / "scripts" / name, repo / "scripts" / name)
    (repo / "docs").mkdir()
    (repo / "docs/proof.txt").write_text("Inhalt aus dem Arbeitsbaum\n")
    (repo / "docs/skizze.txt").write_text("nur in der Skizze\n")
    (repo / "README.en.md").write_text("Nicht hochladen\n")
    (repo / "README.md").write_text(
        '<a href="README.en.md">English</a>\n'
        '<pre>┌─ <a href="docs/skizze.txt#teil">Ebene</a> ─┐</pre>\n'
        "[Beleg](docs/proof.txt#anker), [nochmals](docs/proof.txt)\n"
        "[fehlt](missing.txt) [Ordner](docs) [intern](#anker)\n"
        "[Web](https://example.org/docs) [Web](http://example.org)\n"
    )
    # Git-Ausgaben kontrollieren, ohne ein Test-Repository anzulegen.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = bin_dir / "git"
    git.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        "rev-parse) echo abc1234 ;;\n"
        "ls-files) printf '%s\\n' README.md docs/proof.txt "
        "scripts/readme-walkthrough ;;\n"
        "*) exit 2 ;;\n"
        "esac\n"
    )
    git.chmod(0o755)
    return repo, {"PATH": f"{bin_dir}:{os.environ['PATH']}"}


def test_prepare_default_destination_and_link_selection(
    tmp_path, example_repo
):
    repo, env = example_repo
    target = _prepare(repo, tmp_path, extra_env=env)

    assert target.parent == repo / ".local/var/readme-walkthrough"
    assert re.fullmatch(r"abc1234-\d{6}T\d{4}", target.name)
    assert set(target.iterdir()) == {target / name for name in PERSONAS}
    for persona in PERSONAS:
        files = {
            str(path.relative_to(target / persona))
            for path in (target / persona).rglob("*")
            if path.is_file()
        }
        expected = {"README.md", "root.txt", "uebergabe.txt"}
        if persona == "pruefer":
            expected |= {
                "docs__proof.txt",
                "docs__skizze.txt",
                "dateien.txt",
            }
        assert files == expected
    assert (target / "pruefer/docs__proof.txt").read_text() == (
        "Inhalt aus dem Arbeitsbaum\n"
    )


def test_prepare_destination_from_config_file(tmp_path, example_repo):
    repo, env = example_repo
    home = tmp_path / "home"

    target = _prepare(
        repo,
        tmp_path,
        "~/ausgaben",
        extra_env={**env, "HOME": str(home)},
    )

    assert target.parent == home / "ausgaben"
    assert re.fullmatch(r"abc1234-\d{6}T\d{4}", target.name)
    assert not (repo / ".local").exists()


def test_config_lists_all_candidates_and_marks_used(
    tmp_path, example_repo
):
    repo, env = example_repo
    _write_config(tmp_path, "/ziel/aus")

    lines = _run(repo, tmp_path, ["config"], env).stdout.splitlines()

    xdg = _config_file(tmp_path)
    local = repo / ".local/etc/ki-dev/readme-walkthrough"
    assert lines[0] == SEARCH_HEADER
    assert lines[1] == f"  {xdg} (vorhanden, benutzt)"
    assert lines[2] == f"  {local} (fehlt)"
    assert "Ausgabeordner: /ziel/aus" in lines
    assert f"Quelle: {xdg}" in lines
    assert not (tmp_path / "ziel").exists()


def test_config_falls_back_to_repo_local_file(tmp_path, example_repo):
    repo, env = example_repo
    local = repo / ".local/etc/ki-dev/readme-walkthrough"
    local.parent.mkdir(parents=True)
    local.write_text(f"ausgabe = {tmp_path / 'repo-ziel'}\n")

    result = _run(repo, tmp_path, ["config"], env)

    assert f"  {local} (vorhanden, benutzt)" in result.stdout
    assert f"Ausgabeordner: {tmp_path / 'repo-ziel'}" in result.stdout
    target = _prepare(repo, tmp_path, extra_env=env)
    assert target.parent == tmp_path / "repo-ziel"


def test_unset_xdg_uses_home_config_candidate(tmp_path, example_repo):
    repo, env = example_repo
    home = tmp_path / "home"
    home_config = home / ".config/ki-dev/readme-walkthrough"
    home_config.parent.mkdir(parents=True)
    home_config.write_text(f"ausgabe = {tmp_path / 'home-ziel'}\n")

    result = _run(
        repo,
        tmp_path,
        ["config"],
        {**env, "HOME": str(home), "XDG_CONFIG_HOME": ""},
    )

    assert result.stdout.splitlines()[1] == (
        f"  {home_config} (vorhanden, benutzt)"
    )


def test_prepare_reports_search_on_stderr_and_matches_config(
    tmp_path, example_repo
):
    repo, env = example_repo
    _write_config(tmp_path, str(tmp_path / "ziel"))

    result = _run(repo, tmp_path, ["prepare"], env)
    config = _run(repo, tmp_path, ["config"], env)

    assert SEARCH_HEADER in result.stderr
    assert "vorhanden, benutzt" in result.stderr
    assert "docs/readme-leitlinie.de.md" in result.stderr
    target = Path(result.stdout.strip())
    assert result.stdout.count("\n") == 1
    assert target.parent == tmp_path / "ziel"
    assert f"Ausgabeordner: {target.parent}" in config.stdout


def test_invalid_config_stops_without_fallback(tmp_path, example_repo):
    repo, env = example_repo
    _write_config(tmp_path, "")

    for args in (["config"], ["prepare"]):
        result = _run(repo, tmp_path, args, env, check=False)
        assert result.returncode == 1
        assert (
            f"{_config_file(tmp_path)}: Eintrag ausgabe"
            in result.stderr
        )
    assert not (repo / ".local/var").exists()


def test_duplicate_output_entry_is_rejected(tmp_path, example_repo):
    repo, env = example_repo
    _write_config(tmp_path, "/a")
    _config_file(tmp_path).write_text("ausgabe = /a\nausgabe = /b\n")

    result = _run(repo, tmp_path, ["config"], env, check=False)

    assert result.returncode == 1
    assert "ausgabe ist mehrfach gesetzt" in result.stderr


def test_config_command_without_file_shows_default(
    tmp_path, example_repo
):
    repo, env = example_repo

    result = _run(repo, tmp_path, ["config"], env)

    assert f"  {_config_file(tmp_path)} (fehlt)" in result.stdout
    assert (
        f"Ausgabeordner: {repo / '.local/var/readme-walkthrough'}"
        in result.stdout
    )
    assert "Quelle: Standard" in result.stdout
    assert not (repo / ".local").exists()


@pytest.mark.parametrize(
    "args",
    [[], ["unknown"], ["prepare", "extra"], ["config", "extra"]],
)
def test_rejects_unsupported_commands(tmp_path, args):
    result = subprocess.run(
        [str(REPO / "scripts/readme-walkthrough"), *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "Aufruf:" in result.stderr
