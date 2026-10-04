"""git-Aufrufe für Journal und Projekt-Repo über Plumbum.

bd kann aus einem Git-Hook heraus laufen (post-merge ruft bd hooks
run); die dabei geerbten repo-lokalen GIT_*-Variablen würden
git -C <journal> auf das Projekt-Repo umlenken. Entfernt wird deshalb
die Liste aus ``git rev-parse --local-env-vars``; die Identität
(GIT_AUTHOR_*, GIT_COMMITTER_*) bleibt erhalten.
"""

from __future__ import annotations

from pathlib import Path

from plumbum import local
from plumbum.commands.processes import (
    CommandNotFound,
    ProcessExecutionError,
    ProcessTimedOut,
)

GIT_TIMEOUT = 10
_LOCAL_ENV_VARS = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_CONFIG",
    "GIT_CONFIG_PARAMETERS",
    "GIT_CONFIG_COUNT",
    "GIT_OBJECT_DIRECTORY",
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_GRAFT_FILE",
    "GIT_INDEX_FILE",
    "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE",
    "GIT_PREFIX",
    "GIT_INTERNAL_SUPER_PREFIX",
    "GIT_SHALLOW_FILE",
    "GIT_COMMON_DIR",
)


class GitError(RuntimeError):
    """git fehlt, überschreitet die Frist oder endet unerwartet."""


def run_git(
    directory: Path,
    *args: str,
    retcode: int | tuple[int, ...] = 0,
    config: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Führt git -C directory [-c k=v ...] args aus; Exitcode, stdout.

    config überschreibt Einstellungen nur für diesen Aufruf. Die
    Fehlermeldung nennt Unterbefehl und Exitcode, nicht die Ausgabe:
    sie kann Issue-Inhalte enthalten.
    """
    command = args[0]
    overrides = [
        option
        for key, value in (config or {}).items()
        for option in ("-c", f"{key}={value}")
    ]
    try:
        with local.env():
            for name in _LOCAL_ENV_VARS:
                local.env.pop(name, None)
            code, stdout, _ = local["git"][
                "-C", str(directory), *overrides, *args
            ].run(retcode=retcode, timeout=GIT_TIMEOUT)
    except CommandNotFound as exc:
        raise GitError("git nicht gefunden") from exc
    except ProcessTimedOut as exc:
        raise GitError(f"git {command}: über {GIT_TIMEOUT} s") from exc
    except ProcessExecutionError as exc:
        raise GitError(f"git {command}: Exit {exc.retcode}") from exc
    return code, stdout
