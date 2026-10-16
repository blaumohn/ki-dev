"""scripts/render-readme.py: README-Abschnitte aus readme-scripts."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from plumbum import local

ROOT = Path(__file__).resolve().parents[1]
RENDER = "scripts/render-readme.py"
DE = "readme-scripts/1-setup.sh"
EN = "readme-scripts/en/1-setup.sh"
READMES = ("README.md", "README.en.md")


@pytest.fixture
def repo(tmp_path):
    scripts = (
        path.relative_to(ROOT)
        for path in (ROOT / "readme-scripts").rglob("*.sh")
    )
    for name in (RENDER, *scripts, *READMES):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, tmp_path / name)
    return tmp_path


def test_readmes_match_scripts():
    code, _, err = _render(ROOT, "--check")
    assert code == 0, err


@pytest.mark.parametrize("name", READMES)
def test_changed_block_fails_check_and_is_rewritten(repo, name):
    readme = repo / name
    original = readme.read_text()
    readme.write_text(original.replace("make demo", "make dem0", 1))
    code, _, err = _render(repo, "--check")
    assert code == 1
    assert err == (
        f"{name}: weicht ab; "
        ".venv/bin/python scripts/render-readme.py ausführen\n"
    )
    assert _render(repo)[0] == 0
    assert readme.read_text() == original


def test_comment_lines_become_prose(repo):
    (repo / DE).write_text("# Erklärung\n#\n# ```bash\necho a\n# ```\n")
    (repo / EN).write_text("# Note\n#\n# ```bash\necho a\n# ```\n")
    assert _render(repo)[0] == 0
    assert "Erklärung\n\n```bash\necho a\n```\n<!--" in (
        repo / "README.md"
    ).read_text()


def test_missing_script_fails(repo):
    (repo / EN).unlink()
    code, _, err = _render(repo, "--check")
    assert code == 1
    assert f"README.en.md: Skript {EN} fehlt" in err
    assert f"{DE} hat keine Entsprechung in readme-scripts/en/" in err


@pytest.mark.parametrize("name", READMES)
def test_script_without_block_fails(repo, name):
    readme = repo / name
    script = DE if name == "README.md" else EN
    marker = f"<!-- readme-script: {script} -->"
    readme.write_text(readme.read_text().replace(marker, ""))
    code, _, err = _render(repo, "--check")
    assert code == 1
    assert f"{name}: kein Block für {script}" in err


def test_commands_differ_between_languages(repo):
    en = repo / EN
    en.write_text(en.read_text().replace("make demo", "make test"))
    code, _, err = _render(repo, "--check")
    assert code == 1
    assert f"{DE} und {EN}: Befehle weichen voneinander ab" in err


def test_staged_german_change_needs_english(repo):
    git = local["git"]
    git.run(args=["-C", repo, "init", "-q"], retcode=0, timeout=10)
    git.run(args=["-C", repo, "add", DE], retcode=0, timeout=10)
    assert _render(repo, "--check")[0] == 0
    code, _, err = _render(repo, "--check", "--staged")
    assert code == 1
    assert f"{DE} geändert, aber {EN} nicht mit committet" in err
    git.run(args=["-C", repo, "add", EN], retcode=0, timeout=10)
    assert _render(repo, "--check", "--staged")[0] == 0


def _render(root, *args):
    return local[sys.executable].run(
        args=[root / RENDER, *args], retcode=None, timeout=20
    )
