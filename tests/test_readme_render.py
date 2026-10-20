"""scripts/render-readme.py: README-Abschnitte aus readme-scripts."""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

import pytest
from plumbum import local

ROOT = Path(__file__).resolve().parents[1]
RENDER = "scripts/render-readme.py"
RESULTS_MODULE = "scripts/readme_results.py"
DE = "readme-scripts/1-setup.sh"
EN = "readme-scripts/en/1-setup.sh"
READMES = ("README.md", "README.en.md")
LATER = "2026-10-21T09:30:00Z"
CHECK = "make readme-check"
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
    for name in (RENDER, RESULTS_MODULE, *scripts, *READMES):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, tmp_path / name)
    return tmp_path


@pytest.fixture
def results(tmp_path):
    directory = tmp_path / "ergebnisse"
    directory.mkdir()
    return directory


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
    # Ausgabeblock aus dem letzten Lauf bleibt ohne --write dahinter.
    block = BLOCK_RE.search((repo / "README.md").read_text())
    assert "Erklärung\n\n```bash\necho a\n```\n" in block.group(0)


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


def test_without_write_status_stays(repo, results):
    _result(results, "1-setup", "passed", auszug=["{", "}"])
    assert _render(repo, "--write", results)[0] == 0
    written = {name: (repo / name).read_text() for name in READMES}
    assert _render(repo, "--check")[0] == 0
    assert _render(repo)[0] == 0
    for name in READMES:
        assert (repo / name).read_text() == written[name]


def test_new_block_starts_not_run(repo):
    readme = repo / "README.md"
    readme.write_text(
        BLOCK_RE.sub(
            f"<!-- readme-script: {DE} -->\n<!-- /readme-script -->\n",
            readme.read_text(),
        )
    )
    assert _render(repo)[0] == 0
    assert (
        f"<!-- readme-script: {DE} -->\n"
        "> nicht ausgeführt · selbst prüfen: make readme-check\n\n"
    ) in readme.read_text()


def test_missing_result_is_not_run(repo, results):
    assert _render(repo, "--write", results)[0] == 0
    assert (
        "> nicht ausgeführt · selbst prüfen: make readme-check\n"
        in (repo / "README.md").read_text()
    )
    assert "> not run · verify: make readme-check\n" in (
        repo / "README.en.md"
    ).read_text()


def test_passed_writes_output_after_bash(repo, results):
    _result(results, "1-setup", "passed", auszug=['"status": "passed"'])
    assert _render(repo, "--write", results)[0] == 0
    for name, line in (
        ("README.md", f"> ✅ bestanden · selbst prüfen: {CHECK}"),
        ("README.en.md", f"> ✅ passed · verify: {CHECK}"),
    ):
        block = _block(repo / name)
        assert block.splitlines()[1] == line
        assert (
            "make demo\n```\n\n```text\n"
            '"status": "passed"\n```\n\n`round_id: 2`'
        ) in block
        assert "2026-" not in block


def test_failed_has_no_output_block(repo, results):
    _result(results, "1-setup", "failed")
    assert _render(repo, "--write", results)[0] == 0
    de, en = (_block(repo / name) for name in READMES)
    assert f"> ❌ fehlgeschlagen · selbst prüfen: {CHECK}" in de
    assert "> ❌ failed · verify: make readme-check" in en
    assert "```text" not in de


def test_stub_shows_reason_per_language(repo, results):
    reasons = {"grund_de": "braucht X", "grund_en": "needs X"}
    _result(results, "1-setup", "stub", **reasons)
    assert _render(repo, "--write", results)[0] == 0
    assert (
        "> ⏳ ungeprüft · braucht X · selbst prüfen: make readme-check"
        in _block(repo / "README.md")
    )
    assert "> ⏳ not checked · needs X · verify: make readme-check" in (
        _block(repo / "README.en.md")
    )


def test_parameters_share_one_line(repo, results):
    entries = [
        _entry("1-setup", "passed", parameter={"executor": "mock"}),
        _entry("1-setup", "skipped", parameter={"executor": "claude"}),
    ]
    (results / "1-setup.json").write_text(json.dumps(entries))
    assert _render(repo, "--write", results)[0] == 0
    assert (
        "> ✅ mock · ⏳ claude · selbst prüfen: make readme-check"
        in _block(repo / "README.md")
    )


def test_two_writes_give_the_same_readme(repo, results):
    _result(results, "1-setup", "passed", auszug=["x"])
    assert _render(repo, "--write", results)[0] == 0
    first = (repo / "README.md").read_text()
    _result(results, "1-setup", "passed", auszug=["x"], datum=LATER)
    assert _render(repo, "--write", results)[0] == 0
    assert (repo / "README.md").read_text() == first


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ({"ergebnis": "gruen"}, "1-setup.json: 0/ergebnis: enum"),
        ({"ergebnis": "stub"}, "1-setup.json: 0: required"),
        ({"ergebnis": "failed", "auszug": ["x"]}, "json: 0: not"),
        ({"skript": "2-runtime.sh"}, "2-runtime.sh statt 1-setup"),
    ],
)
def test_invalid_result_fails_without_writing(
    repo, results, entry, message
):
    original = (repo / "README.md").read_text()
    (results / "1-setup.json").write_text(
        json.dumps([_entry("1-setup", "passed") | entry])
    )
    code, _, err = _render(repo, "--write", results)
    assert code == 1
    assert message in err
    assert (repo / "README.md").read_text() == original


def test_result_without_script_fails(repo, results):
    _result(results, "9-fehlt", "passed")
    code, _, err = _render(repo, "--write", results)
    assert code == 1
    assert "9-fehlt.json: kein README-Skript 9-fehlt.sh" in err


def test_text_block_in_output_slot_fails(repo):
    for script in (DE, EN):
        path = repo / script
        path.write_text(
            path.read_text().replace(
                "# ```\n#\n# `round_id",
                "# ```\n#\n# ```text\n# x\n# ```\n#\n# `round_id",
            )
        )
    code, _, err = _render(repo, "--check")
    assert code == 1
    assert f"{DE}: text-Block direkt nach dem letzten bash-Block" in err


def _result(results, stem, ergebnis, **fields):
    entry = _entry(stem, ergebnis) | fields
    (results / f"{stem}.json").write_text(json.dumps([entry]))


def _entry(stem, ergebnis, **fields):
    return {
        "skript": f"{stem}.sh",
        "parameter": {},
        "ergebnis": ergebnis,
        "datum": "2026-10-20T08:00:00Z",
    } | fields


def _block(readme):
    return BLOCK_RE.search(readme.read_text()).group(0)


def _render(root, *args):
    return local[sys.executable].run(
        args=[root / RENDER, *map(str, args)], retcode=None, timeout=20
    )
