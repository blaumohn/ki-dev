"""Lokale CLIs mit dem gemeinsamen Versionsstand vergleichen."""

from __future__ import annotations

from pathlib import Path

import pytest
from plumbum import CommandNotFound, local

from ki_dev.adapter.executors.claude_cli import ClaudeCliAdapter
from ki_dev.adapter.executors.codex_cli import CodexCliAdapter


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
