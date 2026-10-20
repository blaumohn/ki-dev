"""Profil aus Schritt 3 der README: das HERE-Doc in readme-scripts.

readme-scripts/4-rollen.sh schreibt es mit cat <<'EOF' in den
Arbeits-Worktree; die README zeigt genau diese Zeilen. Geprüft wird ohne
Docker, dass es gültiges TOML ist und DE und EN dieselben Werte tragen
(die Kommentare sind je Sprache eigen).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (
    "readme-scripts/4-rollen.sh",
    "readme-scripts/en/4-rollen.sh",
)
HERE_DOC = re.compile(
    r"^cat >\.ki-dev/profiles/default\.toml <<'EOF'\n(.*?)^EOF$",
    re.MULTILINE | re.DOTALL,
)


def profile(script: str) -> dict:
    match = HERE_DOC.search((ROOT / script).read_text())
    assert match, f"{script}: kein HERE-Doc für das Profil"
    return tomllib.loads(match.group(1))


def test_profile_is_toml_with_both_roles():
    shown = profile(SCRIPTS[0])
    assert shown["worker"]["executor"] == "codex"
    assert shown["review"]["executor"] == "claude"
    assert shown["finalization"]["target_workdir"] == "../calc"


def test_profile_values_match_between_languages():
    assert profile(SCRIPTS[0]) == profile(SCRIPTS[1])
