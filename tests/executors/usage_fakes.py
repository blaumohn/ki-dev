"""Lokale CLI-Doubles fuer Verbrauchstests, ohne Modellzugriff."""

from __future__ import annotations

import sys
from pathlib import Path


def write_usage_cli(
    directory: Path,
    provider: str,
    version: str,
    output: str,
    *,
    exit_code: int = 0,
) -> tuple[Path, Path]:
    """CLI mit realistischer Versionsantwort und festem Turnergebnis.

    Die Aufrufspur enthaelt nur 'version'/'turn', keine Argumente,
    Prompts oder Antworten. Das Schreiben startet keinen Prozess.
    """
    version_output = (
        f"codex-cli {version}"
        if provider == "codex"
        else f"{version} (Claude Code)"
    )
    executable = directory / f"fake-{provider}"
    trace = directory / f"{provider}-calls.txt"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "is_version = sys.argv[1:] == ['--version']\n"
        f"with open({str(trace)!r}, 'a') as trace:\n"
        "    trace.write('version\\n' if is_version else 'turn\\n')\n"
        "if is_version:\n"
        f"    print({version_output!r})\n"
        "else:\n"
        "    sys.stdin.read()\n"
        f"    print({output!r})\n"
        f"    sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable, trace
