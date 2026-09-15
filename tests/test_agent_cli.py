from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_agent_cli():
    path = Path(__file__).parents[1] / "docker" / "agent" / "agent-cli.py"
    spec = importlib.util.spec_from_file_location("agent_cli", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_claude_loads_only_container_settings():
    agent_cli = _load_agent_cli()

    args = agent_cli.rewrite_args("claude", ["--print", "Hallo"])

    assert args[:5] == [
        "--dangerously-skip-permissions",
        "--setting-sources",
        "",
        "--settings",
        "/home/agent/.claude/settings.json",
    ]
    assert args[5:] == ["--print", "Hallo"]


def test_interactive_claude_loads_container_settings():
    agent_cli = _load_agent_cli()

    assert agent_cli.rewrite_args("claude", []) == [
        "--dangerously-skip-permissions",
        "--setting-sources",
        "",
        "--settings",
        "/home/agent/.claude/settings.json",
    ]


def test_claude_diagnostics_remain_passthrough():
    agent_cli = _load_agent_cli()

    assert agent_cli.rewrite_args("claude", ["auth", "status"]) == ["auth", "status"]
