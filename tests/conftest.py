"""Gemeinsame Testumgebung."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def claude_quota_dir(tmp_path_factory, monkeypatch):
    """5h-Messwerte des Claude-Adapters nie unter ``~/.cache``."""
    root = tmp_path_factory.mktemp("claude-quota")
    monkeypatch.setattr(
        "ki_dev.adapter.executors.claude_cli.DEFAULT_QUOTA_DIR", root
    )
    return root
