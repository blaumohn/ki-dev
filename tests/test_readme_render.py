"""scripts/render-readme.py: README-Abschnitte aus readme-scripts."""

from __future__ import annotations

import re
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
STATUS = "readme-scripts/status.toml"
BLOCK_RE = re.compile(
    r"^<!-- readme-script: \S*1-setup\.sh -->\n"
    r".*?^<!-- /readme-script -->\n",
    re.MULTILINE | re.DOTALL,
)


@pytest.fixture
def repo(tmp_path):
    scripts = (
        path.relative_to(ROOT)
        for path in (ROOT / "readme-scripts").rglob("*.sh")
    )
    for name in (RENDER, STATUS, *scripts, *READMES):
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
    # Codezeile im Block, nicht die Erwähnung im Kopf
    changed = original.replace("\nmake demo\n", "\nmake dem0\n", 1)
    readme.write_text(changed)
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


def test_status_line_is_first_block_line_in_both_languages(repo):
    (repo / STATUS).write_text(
        '["1-setup.sh"]\nstatus = "unchecked"\ncommand = "make demo"\n'
        '["2-runtime.sh"]\nstatus = "unchecked"\ncommand = "x"\n'
        '["3-review-gate.sh"]\nstatus = "xfail"\n'
        'date = "2026-01-02"\ncommand = "pytest spec"\n'
    )
    assert _render(repo)[0] == 0
    de = (repo / "README.md").read_text()
    en = (repo / "README.en.md").read_text()
    assert (
        f"<!-- readme-script: {DE} -->\n"
        "> ⬜ nicht ausgeführt · selbst prüfen: make demo\n\n"
    ) in de
    assert (
        f"<!-- readme-script: {EN} -->\n"
        "> ⬜ not run · verify: make demo\n\n"
    ) in en
    assert (
        "> ❌ rot, erwartet (Spezifikation) · 2026-01-02 · "
        "selbst prüfen: pytest spec · [Prüfstand](#prüfstand)\n\n"
    ) in de
    assert (
        "> ❌ red, expected (spec) · 2026-01-02 · verify: pytest spec"
        " · [test bench](#test-bench)\n\n"
    ) in en


def test_passed_status_shows_symbol_date_and_command(repo):
    _set_status(repo, '["1-setup.sh"]', "passed", 'date = "2026-10-16"')
    assert _render(repo)[0] == 0
    de = (repo / "README.md").read_text()
    line = "> ✅ bestanden · 2026-10-16 · selbst prüfen: make demo\n"
    assert line in de
    assert "> ✅ passed · 2026-10-16 · verify: make demo\n" in (
        repo / "README.en.md"
    ).read_text()


def test_script_without_status_entry_fails(repo):
    status = repo / STATUS
    status.write_text(status.read_text().split('["2-runtime.sh"]')[0])
    code, _, err = _render(repo, "--check")
    assert code == 1
    assert "kein Eintrag für readme-scripts/2-runtime.sh" in err


def test_status_entry_without_script_fails(repo):
    status = repo / STATUS
    status.write_text(
        status.read_text() + '\n["9-fehlt.sh"]\nstatus = "draft"\n'
    )
    code, _, err = _render(repo, "--check")
    assert code == 1
    assert "Eintrag 9-fehlt.sh ohne Skript" in err


def test_unknown_status_fails(repo):
    _set_status(repo, '["1-setup.sh"]', "gruen")
    code, _, err = _render(repo, "--check")
    assert code == 1
    assert "1-setup.sh: unbekannter status 'gruen'" in err


@pytest.mark.parametrize("status", ["passed", "xfail"])
def test_dated_status_without_date_fails(repo, status):
    _set_status(repo, '["1-setup.sh"]', status)
    code, _, err = _render(repo, "--check")
    assert code == 1
    assert f"1-setup.sh: {status} ohne date" in err


def test_draft_without_block_is_skipped_with_note(repo):
    _set_status(repo, '["1-setup.sh"]', "draft")
    for name in READMES:
        readme = repo / name
        readme.write_text(BLOCK_RE.sub("", readme.read_text()))
    code, _, err = _render(repo, "--check")
    assert code == 0
    for script in (DE, EN):
        assert f"[i] {script}: Entwurf, übersprungen" in err


def test_draft_with_block_fails(repo):
    _set_status(repo, '["1-setup.sh"]', "draft")
    code, _, err = _render(repo, "--check")
    assert code == 1
    assert f"README.md: Entwurf {DE} darf keinen Block haben" in err


def _set_status(repo, header, status, *extra):
    """Ersetzt status (und ergänzt Zeilen) im Eintrag unter header."""
    status_file = repo / STATUS
    head, _, rest = status_file.read_text().partition(header + "\n")
    _, _, tail = rest.partition("command")
    lines = "\n".join([f'status = "{status}"', *extra, "command"])
    status_file.write_text(f"{head}{header}\n{lines}{tail}")


def _render(root, *args):
    return local[sys.executable].run(
        args=[root / RENDER, *args], retcode=None, timeout=20
    )
