"""Isolierte Umgebung für Anforderungstests über die öffentliche CLI.

Jeder Test erhält ein eigenes Git-Repo (Zweig ``main``), ein leeres
HOME und eine Umgebung ohne geerbte Zugangsdaten. ``claude``, ``codex``
und ``docker`` sind durch Attrappen ersetzt, die jeden Aufruf
protokollieren und scheitern: Der Standardlauf startet keinen Anbieter,
und ein trotzdem versuchter Start lässt den Test fehlschlagen.
``PYTHONPATH`` zeigt fest auf ``src`` dieses Checkouts: Geprüft wird der
ausgecheckte Stand, auch wenn das venv eine ältere, nicht editierbare
Kopie enthält (Agent-Image, docker/agent/Dockerfile).
"""

from __future__ import annotations

import os
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

from plumbum import CommandNotFound, ProcessTimedOut, local

from tests.spec.evidence import Blocked, Evidence

SOURCE = Path(__file__).resolve().parents[2] / "src"
PROVIDERS = ("claude", "codex", "docker")
IDENTITY = {
    "GIT_AUTHOR_NAME": "spec",
    "GIT_AUTHOR_EMAIL": "spec@example.invalid",
    "GIT_COMMITTER_NAME": "spec",
    "GIT_COMMITTER_EMAIL": "spec@example.invalid",
}
PROVIDER_STUB = """#!/bin/sh
printf '%s\\n' "$(basename "$0") $*" >> {log}
exit 97
"""


@dataclass(frozen=True)
class Outcome:
    argv: tuple[str, ...]
    code: int
    stdout: str
    stderr: str


class Sandbox:
    """Wegwerf-Repo unter ``base/repo`` mit eigener Umgebung."""

    def __init__(self, base: Path, evidence: Evidence):
        self.base = base
        self.repo = base / "repo"
        self.evidence = evidence
        self._bin = base / "bin"
        self._provider_log = base / "provider-calls.log"
        self.env = self._environment()
        self._install_provider_stubs()
        self.prepare(["git", "init", "-q", "-b", "main", self.repo])

    def run(
        self, argv, cwd: Path | None = None, timeout=120
    ) -> Outcome:
        """Öffentlichen Befehl ausführen und als Beleg festhalten."""
        self.evidence.command(argv)
        outcome = self._execute(argv, cwd or self.repo, timeout)
        self._assert_no_provider_started()
        return outcome

    def prepare(self, argv, cwd: Path | None = None, timeout=60):
        """Vorbereitung ohne Beleg; jeder Fehler ist Infrastruktur."""
        outcome = self._execute(argv, cwd or self.base, timeout)
        if outcome.code != 0:
            raise Blocked(
                "infrastructure",
                f"Vorbereitung {shlex.join(outcome.argv)} "
                f"endet mit {outcome.code}",
            )
        return outcome

    def write(self, relative: str, text: str) -> Path:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def commit(self, message: str) -> None:
        self.prepare(["git", "add", "-A"], cwd=self.repo)
        self.prepare(
            ["git", "commit", "-q", "-m", message], cwd=self.repo
        )

    def _environment(self) -> dict[str, str]:
        home = self.base / "home"
        tmp = self.base / "tmp"
        for directory in (home, tmp):
            directory.mkdir(parents=True)
        venv_bin = Path(sys.executable).parent
        path = os.pathsep.join(
            [str(self._bin), str(venv_bin), os.environ["PATH"]]
        )
        return {
            "PATH": path,
            "PYTHONPATH": str(SOURCE),
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_DATA_HOME": str(home / ".local/share"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_STATE_HOME": str(home / ".local/state"),
            "TMPDIR": str(tmp),
            "LANG": "C.UTF-8",
            "GIT_CONFIG_NOSYSTEM": "1",
            **IDENTITY,
        }

    def _install_provider_stubs(self) -> None:
        self._bin.mkdir()
        stub = PROVIDER_STUB.format(
            log=shlex.quote(str(self._provider_log))
        )
        for name in PROVIDERS:
            path = self._bin / name
            path.write_text(stub)
            path.chmod(0o755)

    def _execute(self, argv, cwd: Path, timeout) -> Outcome:
        argv = tuple(map(str, argv))
        with local.env(), local.cwd(cwd):
            local.env.clear()
            local.env.update(**self.env)
            try:
                code, out, err = local[argv[0]].run(
                    args=argv[1:], retcode=None, timeout=timeout
                )
            except (CommandNotFound, FileNotFoundError) as error:
                raise Blocked(
                    "infrastructure",
                    f"{argv[0]} nicht startbar: {type(error).__name__}",
                ) from error
            except ProcessTimedOut as error:
                raise Blocked(
                    "timeout", f"{shlex.join(argv)} nach {timeout} s"
                ) from error
        return Outcome(argv, code, out, err)

    def _assert_no_provider_started(self) -> None:
        if not self._provider_log.exists():
            return
        calls = self._provider_log.read_text().splitlines()
        raise AssertionError(
            "Anbieter im Standardlauf gestartet: " + "; ".join(calls)
        )
