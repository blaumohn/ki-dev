"""Beispielprofil der README: gültig, günstig, ohne Sitzungs-IDs.

readme-scripts/4-rollen.sh schreibt es mit cat <<'EOF' in den
Arbeits-Worktree; die README zeigt diese Zeilen. Geprüft wird ohne
Docker, dass es ein gültiges Profil ist, DE und EN dieselben Werte
tragen (die Kommentare sind je Sprache eigen) und es die günstigsten
Modelle ohne vorbereitete Sitzungen nutzt.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from ki_dev.flow_ops.implement.cli import load_profile
from ki_dev.tool_versions import load_tool_versions

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


def test_profile_uses_low_cost_pins_and_new_sessions():
    """Das Beispiel läuft mit echten Agenten zu geringen Kosten: je
    Rolle das Modell aus tool-versions.json, Effort ``low`` und keine
    ``session_id`` (ki-dev legt die Sitzungen an)."""
    pins = load_tool_versions()
    shown = profile(SCRIPTS[0])
    assert shown["worker"]["model"] == pins["CODEX_LOW_COST_MODEL"]
    assert shown["review"]["model"] == pins["CLAUDE_LOW_COST_MODEL"]
    for role in ("worker", "review"):
        assert shown[role]["effort"] == "low"
        assert "session_id" not in shown[role]


def test_profile_is_a_valid_run_configuration(tmp_path):
    path = tmp_path / "default.toml"
    match = HERE_DOC.search((ROOT / SCRIPTS[0]).read_text())
    path.write_text(match.group(1), encoding="utf-8")
    load_profile(path)
