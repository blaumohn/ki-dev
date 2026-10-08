"""Relative Links und Anker der öffentlichen Doku sind gültig.

Geprüft werden README.md, README.en.md und ``docs/*.md`` (ohne
Unterordner; ``docs/architecture`` ist Verlauf).
Anker folgen der GitHub-Schreibweise für Überschriften.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
DOCS = [
    ROOT / "README.md",
    ROOT / "README.en.md",
    *sorted((ROOT / "docs").glob("*.md")),
]
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)
FENCE = re.compile(r"^```.*?^```", re.M | re.S)


def _slug(heading: str) -> str:
    text = heading.replace("`", "").strip().lower()
    text = "".join(ch for ch in text if ch.isalnum() or ch in " -_")
    return text.replace(" ", "-")


def _anchors(path: Path) -> set[str]:
    text = FENCE.sub("", path.read_text(encoding="utf-8"))
    return {_slug(h) for h in HEADING.findall(text)}


def _links(path: Path) -> list[str]:
    text = FENCE.sub("", path.read_text(encoding="utf-8"))
    return [
        target
        for target in LINK.findall(text)
        if not re.match(r"^[a-z]+:", target)
    ]


@pytest.mark.parametrize(
    "doc", DOCS, ids=lambda p: str(p.relative_to(ROOT))
)
def test_relative_links_and_anchors_resolve(doc):
    broken = []
    for target in _links(doc):
        file_part, _, anchor = target.partition("#")
        resolved = (
            (doc.parent / file_part).resolve() if file_part else doc
        )
        if not resolved.exists() or (
            anchor
            and resolved.suffix == ".md"
            and anchor not in _anchors(resolved)
        ):
            broken.append(target)
    assert broken == []


@pytest.mark.parametrize(
    "doc", DOCS, ids=lambda p: str(p.relative_to(ROOT))
)
def test_docs_name_no_loop_command(doc):
    """Die Schleife ist eine Rückkante im Ablauf; den Befehl gibt es
    nicht."""
    assert "ki-dev loop" not in doc.read_text(encoding="utf-8")
