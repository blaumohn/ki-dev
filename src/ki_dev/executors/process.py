"""Gemeinsamer Prozesslauf fuer die CLI-Executor-Adapter.

Ein Aufruf entspricht genau einem Agenten-Turn. Der externe Prozess
wird ueber Plumbum gestartet (vorgesehener Python-Werkzeugsatz aus
Quellen-Bead ki-dev-ablauf-9p4a). Prozessstart, Standardausgabe, Fehlerausgabe,
Exitstatus, Timeout und Start-/Prozessfehler werden hier einheitlich
erfasst. Es gibt keine stillen Fallbacks: jeder Ausgang wird als
expliziter :class:`TurnStatus` zurueckgegeben.
"""

from __future__ import annotations

import time
from pathlib import Path

from plumbum import CommandNotFound, local
from plumbum.commands.processes import ProcessTimedOut

from .contract import TurnResult, TurnStatus

DEFAULT_TIMEOUT_S = 900.0


def run_cli_turn(
    argv: list[str],
    *,
    stdin: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> TurnResult:
    """Starte genau einen CLI-Turn und erfasse den Ausgang.

    Ohne ``cwd``/``env`` erbt der Prozess Arbeitsverzeichnis und
    Umgebung des Aufrufers, inklusive der Anmeldung der bereits
    eingerichteten CLI. Es findet keine API-Schluesselverwaltung und
    kein Login statt.
    """
    argv_t = tuple(argv)
    start = time.monotonic()

    try:
        command = local[argv[0]][tuple(argv[1:])]
    except CommandNotFound as exc:
        return _start_error(
            argv_t, start, f"CLI nicht auffindbar: {exc.program}"
        )

    try:
        exit_code, stdout, stderr = (command << stdin).run(
            retcode=None,
            timeout=timeout_s,
            cwd=cwd,
            env=env,
        )
    except ProcessTimedOut:
        return _outcome(
            argv_t,
            start,
            TurnStatus.TIMEOUT,
            error=f"Zeitueberschreitung nach {timeout_s:g}s",
        )
    except OSError as exc:
        # OSError ist die benannte Fehlerfamilie fuer einen nicht
        # startbaren Kindprozess (CLI nicht ausfuehrbar). Breitere
        # Ausnahmen werden nicht gefangen.
        return _start_error(argv_t, start, str(exc))

    return _finished(argv_t, start, exit_code, stdout, stderr)


def _finished(
    argv: tuple[str, ...],
    start: float,
    exit_code: int,
    stdout: str,
    stderr: str,
) -> TurnResult:
    if exit_code == 0:
        status, error = TurnStatus.OK, None
    else:
        status = TurnStatus.NONZERO_EXIT
        error = f"CLI endete mit Exitstatus {exit_code}"
    return _outcome(
        argv,
        start,
        status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        error=error,
    )


def _start_error(
    argv: tuple[str, ...],
    start: float,
    detail: str,
) -> TurnResult:
    return _outcome(
        argv,
        start,
        TurnStatus.START_ERROR,
        error=f"Prozessstart fehlgeschlagen: {detail}",
    )


def _outcome(
    argv: tuple[str, ...],
    start: float,
    status: TurnStatus,
    *,
    exit_code: int | None = None,
    stdout: str = "",
    stderr: str = "",
    error: str | None = None,
) -> TurnResult:
    return TurnResult(
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        argv=argv,
        duration_s=time.monotonic() - start,
        error=error,
    )
