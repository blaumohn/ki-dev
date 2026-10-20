"""make readme-check: Statuszeilen auch nach gescheitertem Build (bel0).

Fake-CHECK statt docker compose, in einer Kopie der README-Dateien; den
echten Lauf deckt make readme-check auf dem Host ab.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from plumbum import local

ROOT = Path(__file__).resolve().parents[1]
COPY = (
    "Makefile",
    "README.md",
    "README.en.md",
    "src/ki_dev/tool-versions.json",
    "scripts/render-readme.py",
    "scripts/readme_results.py",
)
# build: Exit aus FAKE_BUILD_EXIT; run: legt ein Ergebnis für
# 4-auftrag.sh ab, wie der Container es in /tmp/readme-ergebnisse tut.
FAKE_CHECK = """#!/bin/sh
echo "$*" >>"$FAKE_CHECK_CALLS"
case "$1" in
  build) exit "${FAKE_BUILD_EXIT:-0}" ;;
  run) printf '%s' '[{"skript": "4-auftrag.sh", "parameter": {},
    "ergebnis": "passed", "datum": "2026-10-20T08:00:00Z"}]' \\
    >"$READMECHECK_TMP_DIR/readme-ergebnisse/4-auftrag.json" ;;
esac
"""


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / "repo"
    for name in COPY:
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / name, repo / name)
    shutil.copytree(ROOT / "readme-scripts", repo / "readme-scripts")
    (repo / ".venv").symlink_to(ROOT / ".venv")
    return repo


def test_failed_build_sets_all_not_run(repo, tmp_path):
    code, _, err = _make(repo, tmp_path, FAKE_BUILD_EXIT="3")
    assert code != 0
    assert "Error 3" in err
    assert (tmp_path / "calls").read_text() == "build check\n"
    for name, not_run in (
        ("README.md", "> nicht ausgeführt"),
        ("README.en.md", "> not run"),
    ):
        lines = _status_lines(repo / name)
        assert lines
        assert all(line.startswith(not_run) for line in lines)


def test_run_results_set_status_lines(repo, tmp_path):
    code, _, err = _make(repo, tmp_path)
    assert code == 0, err
    assert (tmp_path / "calls").read_text().splitlines() == [
        "build check",
        "run --rm check",
    ]
    text = (repo / "README.md").read_text()
    block = text.split("readme-scripts/4-auftrag.sh -->\n", 1)[1]
    assert block.startswith("> ✅ bestanden")
    assert (
        text.count("> nicht ausgeführt")
        == len(_status_lines(repo / "README.md")) - 1
    )


def _make(repo, tmp_path, **env):
    check = tmp_path / "fake-check"
    check.write_text(FAKE_CHECK)
    check.chmod(0o755)
    with local.env(FAKE_CHECK_CALLS=str(tmp_path / "calls"), **env):
        return local["make"].run(
            args=["-s", "-C", repo, "readme-check", f"CHECK={check}"],
            retcode=None,
            timeout=60,
        )


def _status_lines(readme: Path) -> list[str]:
    lines = readme.read_text().splitlines()
    return [
        lines[i + 1]
        for i, line in enumerate(lines[:-1])
        if line.startswith("<!-- readme-script:")
    ]
