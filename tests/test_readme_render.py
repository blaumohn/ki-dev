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
GUIDES = ("docs/vertiefung.de.md", "docs/vertiefung.en.md")
LATER = "2026-10-21T09:30:00Z"
TEST = "tests/readme/test_1_setup.sh"
DE_LINK = f'<a href="{TEST}">Test</a>'
EN_LINK = f'<a href="{TEST}">test</a>'
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
    tests = (
        path.relative_to(ROOT)
        for path in (ROOT / "tests/readme").glob("test_*")
    )
    for name in (
        RENDER, RESULTS_MODULE, *scripts, *tests, *READMES, *GUIDES
    ):
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
    changed = original.replace("\nmake setup", "\nmake setop", 1)
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


def test_line_comments_may_differ_between_languages(repo):
    for script, comment in ((DE, "Mock-Lauf"), (EN, "mock run")):
        path = repo / script
        path.write_text(
            path.read_text().replace(
                "\nmake setup", f"\nmake setup  # {comment}"
            )
        )
    code, _, err = _render(repo, "--check")
    assert "Befehle weichen voneinander ab" not in err


def test_commands_differ_between_languages(repo):
    en = repo / EN
    en.write_text(en.read_text().replace("make setup", "make test"))
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
        "\n```\n\n"
        + _status(f"Im letzten Prüflauf nicht ausgeführt · {DE_LINK}")
        + "\n"
    ) in readme.read_text()


def test_missing_result_is_not_run(repo, results):
    assert _render(repo, "--write", results)[0] == 0
    not_run = f"Im letzten Prüflauf nicht ausgeführt · {DE_LINK}"
    assert _status(not_run) + "\n" in (repo / "README.md").read_text()
    assert _status(f"Not run in the last check · {EN_LINK}") in (
        repo / "README.en.md"
    ).read_text()


def test_passed_line_and_output_follow_the_bash_block(repo, results):
    _result(results, "1-setup", "passed", auszug=['"status": "passed"'])
    assert _render(repo, "--write", results)[0] == 0
    passed_de = f"✓ Im leeren Container ausgeführt · {DE_LINK}"
    passed_en = f"✓ Run in an empty container · {EN_LINK}"
    for name, line in (
        ("README.md", _status(passed_de)),
        ("README.en.md", _status(passed_en)),
    ):
        block = _block(repo / name)
        assert not block.splitlines()[1].startswith("<p align=")
        assert (
            f"\n```\n\n{line}\n\n```text\n"
            '"status": "passed"\n```\n'
        ) in block
        assert "2026-" not in block


def test_failed_has_no_output_block(repo, results):
    _result(results, "1-setup", "failed")
    assert _render(repo, "--write", results)[0] == 0
    de, en = (_block(repo / name) for name in READMES)
    failed = f"✗ Im leeren Container fehlgeschlagen · {DE_LINK}"
    assert _status(failed) in de
    assert _status(f"✗ Failed in an empty container · {EN_LINK}") in en
    assert "```text" not in de


def test_stub_shows_reason_per_language(repo, results):
    reasons = {"grund_de": "braucht X", "grund_en": "needs X"}
    _result(results, "1-setup", "stub", **reasons)
    assert _render(repo, "--write", results)[0] == 0
    assert _status(f"○ Ungeprüft: braucht X · {DE_LINK}") in _block(
        repo / "README.md"
    )
    assert _status(f"○ Not checked: needs X · {EN_LINK}") in _block(
        repo / "README.en.md"
    )


def test_parameters_share_one_line(repo, results):
    entries = [
        _entry("1-setup", "passed", parameter={"executor": "mock"}),
        _entry("1-setup", "skipped", parameter={"executor": "claude"}),
    ]
    (results / "1-setup.json").write_text(json.dumps(entries))
    assert _render(repo, "--write", results)[0] == 0
    assert (
        _status(f"Im leeren Container: ✓ mock · ○ claude · {DE_LINK}")
        in _block(repo / "README.md")
    )


def test_without_test_file_no_link(repo, results):
    (repo / TEST).unlink()
    _result(results, "1-setup", "passed")
    assert _render(repo, "--write", results)[0] == 0
    assert _status("✓ Im leeren Container ausgeführt") + "\n" in _block(
        repo / "README.md"
    )


def test_kept_status_follows_the_test_file(repo, results):
    _result(results, "1-setup", "passed")
    assert _render(repo, "--write", results)[0] == 0
    (repo / TEST).rename(repo / "tests/readme/test_1_setup.py")
    assert _render(repo)[0] == 0
    assert _status(
        "✓ Im leeren Container ausgeführt · "
        '<a href="tests/readme/test_1_setup.py">Test</a>'
    ) + "\n" in _block(repo / "README.md")


@pytest.mark.parametrize(
    "former",
    [
        f"> ✅ Im leeren Container ausgeführt · [Test]({TEST})",
        f"<small>✅ Im leeren Container ausgeführt · [Test]({TEST})"
        "</small>",
    ],
)
def test_kept_status_in_former_form_becomes_current(
    repo, results, former
):
    """Eine Statuszeile einer früheren Form (Zitat, ``<small>``, Emoji)
    bleibt erhalten und erscheint beim nächsten Rendern in der
    aktuellen Form."""
    _result(results, "1-setup", "passed")
    assert _render(repo, "--write", results)[0] == 0
    readme = repo / "README.md"
    current = _status(f"✓ Im leeren Container ausgeführt · {DE_LINK}")
    readme.write_text(readme.read_text().replace(current, former))
    assert _render(repo)[0] == 0
    assert f"\n{current}\n" in _block(readme)


def test_stub_reason_is_escaped_in_the_html_line(repo, results):
    reasons = {"grund_de": "braucht <X> & Y", "grund_en": "needs X"}
    _result(results, "1-setup", "stub", **reasons)
    assert _render(repo, "--write", results)[0] == 0
    assert "○ Ungeprüft: braucht &lt;X&gt; &amp; Y · " in _block(
        repo / "README.md"
    )


@pytest.mark.parametrize(
    ("name", "toc", "back"),
    [
        ("README.md", "inhalt", "↑ Zum Inhalt"),
        ("README.en.md", "contents", "↑ Back to contents"),
    ],
)
def test_contents_and_back_links_follow_the_headings(
    repo, name, toc, back
):
    """Inhalt und Rücksprünge entstehen aus den Überschriften: ein neuer
    Unterabschnitt erscheint eingerückt im Inhalt und bekommt seinen
    Rücksprung, ohne Handarbeit."""
    readme = repo / name
    text = readme.read_text()
    heading = next(
        line for line in text.splitlines() if line.startswith("### ")
    )
    readme.write_text(
        text.replace(heading, f"### Neu `x`\n\nText.\n\n{heading}", 1)
    )
    code, _, err = _render(repo, "--check")
    assert code == 1
    assert _render(repo)[0] == 0
    rendered = readme.read_text()
    nav = f'<p align="right"><a href="#{toc}">{back}</a></p>'
    assert "\n  - [Neu `x`](#neu-x)\n" in rendered
    # Nicht mehr alle Unterabschnitte nummeriert: ungeordnete Liste.
    assert "\n  - [Neu `x`](#neu-x)\n  - [1. " in rendered
    assert f"### Neu `x`\n\nText.\n\n{nav}\n\n{heading}" in rendered
    assert _render(repo, "--check")[0] == 0


def test_numbered_subsections_become_an_ordered_list():
    """Heißen alle Unterabschnitte „1. …“, „2. …“, zeigt der Inhalt sie
    als nummerierte Liste; die Nummer steht nicht doppelt im Link."""
    text = (ROOT / "README.md").read_text()
    assert (
        "- [Ausprobieren](#ausprobieren)\n"
        "  1. [Einrichten](#1-einrichten)\n"
        "  2. [Auftrag anlegen](#2-auftrag-anlegen)\n"
    ) in text
    assert "  6. [Ergebnis ansehen](#6-ergebnis-ansehen)\n" in text
    assert "[1. Einrichten]" not in text


def test_hand_edit_in_contents_block_is_replaced(repo):
    readme = repo / "README.md"
    original = readme.read_text()
    readme.write_text(
        original.replace("- [Stand](#stand)\n", "- [Alt](#alt)\n", 1)
    )
    assert _render(repo, "--check")[0] == 1
    assert _render(repo)[0] == 0
    assert readme.read_text() == original


@pytest.mark.parametrize(
    "marker", ["<!-- readme-inhalt -->", "<!-- /readme-inhalt -->"]
)
def test_incomplete_contents_block_fails(repo, marker):
    readme = repo / "README.md"
    original = readme.read_text()
    readme.write_text(original.replace(f"{marker}\n", "", 1))
    code, _, err = _render(repo)
    assert code == 1
    assert "README.md: Inhaltsblock unvollständig oder mehrfach" in err
    assert marker not in readme.read_text()


def test_back_link_only_after_sections_without_subsections(repo):
    lines = (repo / "README.md").read_text().splitlines()
    nav = '<p align="right"><a href="#inhalt">↑ Zum Inhalt</a></p>'
    headings = [
        i
        for i, line in enumerate(lines)
        if line.startswith(("## ", "### "))
    ]
    before = {
        lines[i]: nav in lines[j:i]
        for j, i in zip(headings, headings[1:], strict=False)
    }
    assert before["## Ausprobieren"]  # nach dem Minimalbeispiel
    assert not before["### 1. Einrichten"]  # Ausprobieren hat Schritte
    assert before["### 2. Auftrag anlegen"]
    assert before["## Stand"]
    assert nav not in lines[headings[-1] :]  # letzter Abschnitt
    assert not any(line.startswith(">") for line in lines)


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
                "# ```\n",
                "# ```\n#\n# ```text\n# x\n# ```\n#\n",
            )
        )
    code, _, err = _render(repo, "--check")
    assert code == 1
    assert f"{DE}: text-Block direkt nach dem letzten bash-Block" in err


def test_separate_commands_need_separate_checked_sections(repo):
    """Jeder Befehlsblock braucht einen eigenen Prüfstatus."""
    for script in (DE, EN):
        path = repo / script
        path.write_text(
            path.read_text() + "#\n# ```bash\necho extra\n# ```\n"
        )
    code, _, err = _render(repo, "--check")
    assert code == 1
    assert "mehrere bash-Blöcke" in err


def test_duplicate_source_across_documents_fails(repo):
    guide = repo / GUIDES[0]
    guide.write_text(guide.read_text() + _block(repo / READMES[0]))
    code, _, err = _render(repo, "--check")
    assert code == 1
    assert f"{DE}: mehrfach eingebunden" in err


def test_results_and_links_follow_a_section_into_the_guide(
    repo, results
):
    _result(results, "8-demo", "passed")
    assert _render(repo, "--write", results)[0] == 0
    for name, status, setup in (
        (
            GUIDES[0],
            "✓ Im leeren Container ausgeführt",
            "1-einrichten",
        ),
        (GUIDES[1], "✓ Run in an empty container", "1-set-up"),
    ):
        text = (repo / name).read_text()
        assert status in text
        assert 'href="../tests/readme/test_8_demo.sh"' in text
        readme = (
            "README.en.md" if name.endswith(".en.md") else "README.md"
        )
        assert f"(../{readme}#{setup})" in text
    assert _render(repo, "--check")[0] == 0


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


def _status(status):
    """Statuszeile wie in der README (scripts/readme_results.py)."""
    return f'<p align="right"><sub>{status}</sub></p>'


def _block(readme):
    return BLOCK_RE.search(readme.read_text()).group(0)


def _render(root, *args):
    return local[sys.executable].run(
        args=[root / RENDER, *map(str, args)], retcode=None, timeout=20
    )


def test_live_result_is_marked_and_wins_over_the_container_stub(
    repo, results
):
    """Ein eingecheckter Lauf mit echten Agenten (make readme-live)
    setzt Status und Ausgabe seines Blocks; der Container kann dort nur
    einen Stub liefern und überschreibt ihn nicht."""
    live = repo / "docs/beispiele/echtlauf"
    live.mkdir(parents=True)
    _result(
        live, "9-ergebnis", "passed",
        auszug=["Lauf version-fix: passed"],
    )
    _result(
        results, "9-ergebnis", "stub", grund_de="braucht Agenten",
        grund_en="needs agents",
    )
    assert _render(repo, "--write", results)[0] == 0
    for name, status in (
        ("README.md", "<sub>✓ Mit echten Agenten ausgeführt · <a "),
        ("README.en.md", "<sub>✓ Run with real agents · <a href="),
    ):
        text = (repo / name).read_text()
        assert status in text
        assert "Lauf version-fix: passed" in text
        assert "braucht Agenten" not in text
