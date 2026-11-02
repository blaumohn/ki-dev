"""Gemeinsamer Prozessaufruf fuer die Schrittdelta-Bildung.

Git und ``bd`` werden ueber Plumbum gestartet (vorgesehener
Python-Werkzeugsatz aus Quellen-Bead ki-dev-ablauf-9p4a). Beide CLIs
erhalten das Arbeitsverzeichnis ueber ``-C``; ein Wechsel des
Prozess-Arbeitsordners findet nicht statt. Jeder Fehlausgang wird als
:class:`DeltaCommandError` sichtbar und niemals still verschluckt.
"""

from __future__ import annotations

from dataclasses import dataclass

from plumbum import CommandNotFound, local


class DeltaCommandError(RuntimeError):
    """Ein Git-/``bd``-Aufruf der Deltabildung ist fehlgeschlagen."""


@dataclass(frozen=True)
class CommandOutput:
    """Roh erfasster Ausgang eines einzelnen Prozessaufrufs."""

    argv: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str

    def require_success(self) -> str:
        if self.exit_code == 0:
            return self.stdout
        raise DeltaCommandError(self._failure_message())

    def _failure_message(self) -> str:
        shown = " ".join(self.argv)
        detail = (self.stderr or self.stdout).strip()
        return (
            f"Aufruf endete mit Exitstatus {self.exit_code}: {shown}"
            f"\n{detail}"
        )


# Git des Hosts in Worktrees, die ein Agent schreiben konnte: Hooks und
# fsmonitor wären dessen Code auf dem Host. Checkpoints sind maschinell
# und werden bei der Finalisierung durch commit-tree ersetzt.
HOST_GIT = (
    "git",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "core.fsmonitor=false",
)


def run_command(argv: list[str]) -> CommandOutput:
    """Starte einen Prozess und erfasse den vollstaendigen Ausgang."""
    try:
        command = local[argv[0]][tuple(argv[1:])]
    except CommandNotFound as exc:
        raise DeltaCommandError(
            f"CLI nicht auffindbar: {exc.program}"
        ) from exc

    try:
        exit_code, stdout, stderr = command.run(retcode=None)
    except OSError as exc:
        # OSError ist die benannte Fehlerfamilie fuer einen nicht
        # startbaren Kindprozess. Breitere Ausnahmen werden nicht
        # gefangen.
        raise DeltaCommandError(
            f"Prozessstart fehlgeschlagen: {exc}"
        ) from exc

    return CommandOutput(tuple(argv), exit_code, stdout, stderr)
