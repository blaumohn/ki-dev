"""Lokale CLIs mit dem gemeinsamen Versionsstand vergleichen."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from plumbum import CommandNotFound, local

from ki_dev.adapter.executors.claude_cli import ClaudeCliAdapter
from ki_dev.adapter.executors.codex_cli import CodexCliAdapter
from ki_dev.tool_versions import load_tool_versions


@pytest.mark.parametrize(
    "adapter_type", [ClaudeCliAdapter, CodexCliAdapter]
)
def test_local_cli_matches_pinned_version(adapter_type):
    adapter = adapter_type()
    exe = adapter.default_executable
    try:
        command = local[exe]
    except CommandNotFound:
        pytest.skip(f"{exe} lokal nicht installiert")
    with local.cwd(Path(__file__).resolve().parent):
        raw = command.run(args=["--version"], retcode=0, timeout=10)[1]
    assert adapter.parse_version(raw) == adapter.cli_version_pin


def test_codex_low_cost_model_is_listed_for_the_pinned_version():
    """Der Modellpin des Beispielprofils steht im lokalen
    Modellkatalog derselben Codex-Version (``codex`` legt ihn nach der
    Anmeldung an)."""
    pins = load_tool_versions()
    catalog = Path.home() / ".codex/models_cache.json"
    if not catalog.is_file():
        pytest.skip("kein lokaler Codex-Modellkatalog")
    data = json.loads(catalog.read_text(encoding="utf-8"))
    if data["client_version"] != pins["CODEX_VERSION"]:
        pytest.skip("Modellkatalog einer anderen Codex-Version")
    listed = {
        model["slug"]
        for model in data["models"]
        if model["visibility"] == "list"
    }
    assert pins["CODEX_LOW_COST_MODEL"] in listed


def test_claude_low_cost_model_is_an_alias_of_the_local_catalog():
    """Der Modellpin ist ein Alias im lokalen Claude-Modellkatalog."""
    pins = load_tool_versions()
    catalogs = sorted(
        (Path.home() / ".claude/cache/model-catalog").glob("*.json")
    )
    if not catalogs:
        pytest.skip("kein lokaler Claude-Modellkatalog")
    for catalog in catalogs:
        data = json.loads(catalog.read_text(encoding="utf-8"))
        aliases = data["catalog"]["config"]["provider_alias_targets"]
        assert pins["CLAUDE_LOW_COST_MODEL"] in aliases
