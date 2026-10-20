"""Profil aus Schritt 2 der README = docs/beispiele/default.toml.

readme-scripts/4-auftrag.sh legt die Datei ins Wegwerf-Repo, Schritt 4
startet damit; die README zeigt sie kommentiert. Verglichen werden die
Werte, die Kommentare sind je Sprache eigen.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "docs/beispiele/default.toml"
STEP_2 = re.compile(
    r"^### 2\. .*?^```toml\n(.*?)^```$", re.MULTILINE | re.DOTALL
)


@pytest.mark.parametrize("readme", ["README.md", "README.en.md"])
def test_step_2_shows_the_example_profile(readme):
    block = STEP_2.search((ROOT / readme).read_text())
    assert block, f"{readme}: kein toml-Block in Schritt 2"
    shown = tomllib.loads(block.group(1))
    assert shown == tomllib.loads(PROFILE.read_text())
