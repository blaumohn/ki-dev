"""Standardort der Laufdaten: ``XDG_STATE_HOME/ki-dev/runs/<repo>``.

Nur ki-dev liest und schreibt Laufdaten, Agenten bekommen ihren Auftrag
von ki-dev; ins Repo gehören sie nicht. Je Repo ein Ordner, weil feste
Lauf-IDs (``--run-id version-fix``) sonst zwischen Repos kollidieren.
Alle Worktrees eines Repos teilen ihn: ``resume`` findet den Lauf aus
Hauptcheckout und Arbeits-Worktree.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from ki_dev.deltas import HOST_GIT, run_command


def default_runs_dir(cwd: Path | None = None) -> Path:
    project = _project_root((cwd or Path.cwd()).resolve())
    digest = hashlib.sha256(str(project).encode()).hexdigest()[:8]
    return _state_home() / "ki-dev/runs" / f"{project.name}-{digest}"


def _state_home() -> Path:
    # XDG: relative Werte gelten als nicht gesetzt.
    configured = os.environ.get("XDG_STATE_HOME", "")
    if os.path.isabs(configured):
        return Path(configured)
    return Path.home() / ".local/state"


def _project_root(cwd: Path) -> Path:
    """Wurzel des Hauptcheckouts; ohne Git der Ordner selbst."""
    output = run_command(
        [
            *HOST_GIT,
            "-C",
            str(cwd),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ]
    )
    if output.exit_code != 0:
        return cwd
    return Path(output.stdout.strip()).parent
