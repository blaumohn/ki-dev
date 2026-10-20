"""Ebenen-Skizze der READMEs: als Bild lesbar.

Die Skizze steht als ``<pre>`` mit Links (README-Leitlinie, Regel 7).
Geprüft wird der sichtbare Text ohne Tags: höchstens 72 Zeichen breit,
die rechte Kante aller Kästen in einer Spalte, DE und EN gleich gebaut
(Kästen in denselben Zeilen).
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
READMES = ("README.md", "README.en.md")
PRE = re.compile(r"^<pre>\n(.*?)\n</pre>$", re.M | re.S)
TAG = re.compile(r"<[^>]+>")
EDGE = {"┌": "┐", "│": "│", "└": "┘"}


def _sketch(name: str) -> list[str]:
    blocks = PRE.findall((ROOT / name).read_text(encoding="utf-8"))
    assert len(blocks) == 1, f"{name}: genau eine <pre>-Skizze erwartet"
    return html.unescape(TAG.sub("", blocks[0])).split("\n")


def _box_rows(lines: list[str]) -> list[int]:
    return [i for i, line in enumerate(lines) if line[:1] in EDGE]


@pytest.mark.parametrize("name", READMES)
def test_sketch_fits_72_columns(name):
    too_wide = [line for line in _sketch(name) if len(line) > 72]
    assert too_wide == []


@pytest.mark.parametrize("name", READMES)
def test_box_edges_share_one_column(name):
    lines = _sketch(name)
    edges = {
        lines[i].rfind(EDGE[lines[i][0]]) for i in _box_rows(lines)
    }
    assert len(edges) == 1


def test_sketch_same_shape_in_both_languages():
    de, en = (_sketch(name) for name in READMES)
    assert len(de) == len(en)
    assert _box_rows(de) == _box_rows(en)
