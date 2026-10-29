"""Bead-Verweise der README: ``<!-- bead: ID … -->`` an einer Lücke.

Die Kurz-IDs (ohne Präfix ``ki-dev-ablauf-``) bleiben unsichtbar, bis
das Beads-Journal veröffentlicht ist und render-readme.py sie
verlinken kann (ki-dev-ablauf-jlk). Damit sie bis dahin nicht
unbemerkt veralten: Jede ID gibt es im Export ``.beads/issues.jsonl``,
keine ist geschlossen, solange ihre Zeile eine Lücke nennt, und DE und
EN nennen dieselben IDs.
Ohne Export (Klon ohne Beads-Daten) entfällt der Abgleich mit Beads.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAIRS = (
    ("README.md", "README.en.md"),
    ("docs/vertiefung.de.md", "docs/vertiefung.en.md"),
)
EXPORT = ROOT / ".beads/issues.jsonl"
PREFIX = "ki-dev-ablauf-"
BEAD = re.compile(r"<!-- bead: ([^>]*?) -->")


def _ids(name: str) -> list[str]:
    text = (ROOT / name).read_text(encoding="utf-8")
    return [i for group in BEAD.findall(text) for i in group.split()]


@pytest.mark.parametrize(("de", "en"), PAIRS)
def test_languages_name_the_same_beads(de, en):
    assert _ids(de) == _ids(en)


def test_readme_names_beads():
    assert _ids("README.md")


@pytest.mark.skipif(not EXPORT.is_file(), reason="kein Beads-Export")
@pytest.mark.parametrize(
    "name", [name for pair in PAIRS for name in pair]
)
def test_beads_exist_and_are_open(name):
    status = {}
    for line in EXPORT.read_text(encoding="utf-8").splitlines():
        if line.strip():
            issue = json.loads(line)
            short = issue["id"].removeprefix(PREFIX)
            status[short] = issue.get("status")
    unknown = [i for i in _ids(name) if i not in status]
    closed = [i for i in _ids(name) if status.get(i) == "closed"]
    assert (unknown, closed) == ([], [])
