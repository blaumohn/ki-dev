"""Bezugsstand der CLI-Adapter gegen die lokal installierten CLIs.

Der gepinnte Bezugsstand steht im jeweiligen Adaptermodul und ist
ohne Binaerdatei pruefbar. Zusaetzlich wird - sofern die CLI lokal
vorhanden ist - ``<cli> --version`` gegen genau diesen Stand geprueft.
"""

from __future__ import annotations

import pytest
from plumbum import CommandNotFound, local

from ki_dev.executors import claude_cli, codex_cli

_CASES = [
    ("claude", claude_cli.VERIFIED_CLI_VERSION, "2.1.258"),
    ("codex", codex_cli.VERIFIED_CLI_VERSION, "0.152.1"),
]


@pytest.mark.parametrize(("_exe", "pinned", "expected"), _CASES)
def test_pinned_version_is_documented(_exe, pinned, expected):
    assert pinned == expected


@pytest.mark.parametrize(("exe", "pinned", "_expected"), _CASES)
def test_local_cli_matches_pinned_version(exe, pinned, _expected):
    try:
        command = local[exe]
    except CommandNotFound:
        pytest.skip(f"{exe} lokal nicht installiert")
    assert pinned in command("--version")
