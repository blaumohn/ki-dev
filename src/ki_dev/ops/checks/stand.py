"""Geprüfter Stand des Vorlaufs: Arbeitsbaum und Bead.

Wie ``freeze`` bei ``ki-dev -f implement`` vergleicht step synchron:
Der Vorlauf merkt sich den Stand, eine Review-Antwort bringt den
aktuellen mit; weichen sie ab, nimmt der Planungsablauf die Kante
zurück in den Vorlauf (Wächter ``unchanged``).

- ``tree``: Git-Tree des Arbeitsbaums einschließlich uncommitteter und
  neuer Dateien. Ein temporärer Index lässt den echten Index unberührt;
  ``.gitignore`` gilt, ``.local/`` (Laufzustand und Artefakte von
  ki-dev) und die Antwortdatei des Reviews sind ausgenommen: sie sind
  Eingaben an ki-dev, keine Arbeit.
- ``bead``: sha256 über die Bead-Felder, aus denen die Übergabe
  entsteht.

Der Vorlauf selbst braucht kein Git (ki-dev-ablauf-8is). Ohne
Git-Arbeitsbaum gibt es keinen Stand (``None``) und damit kein PASS;
das ist der einzige Anlass für ``None``, andere git-Fehler bleiben
sichtbar.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from plumbum import CommandNotFound, local
from plumbum.commands.processes import ProcessTimedOut, run_proc

from ki_dev.ops.context.bead_input import BeadInput

GIT_TIMEOUT_S = 30
_EXCLUDED = ":(exclude).local"


class StandError(RuntimeError):
    """Der Stand ist nicht ermittelbar; ohne ihn gibt es kein PASS."""


def current_stand(
    project_root: Path,
    issue: BeadInput,
    exclude: Path | None = None,
) -> dict[str, str] | None:
    """Stand jetzt: Tree des Arbeitsbaums und Fingerabdruck des Beads;
    ``None`` außerhalb eines Git-Arbeitsbaums."""
    if not _inside_worktree(project_root):
        return None
    return {
        "tree": worktree_tree(project_root, exclude),
        "bead": bead_digest(issue),
    }


def bead_digest(issue: BeadInput) -> str:
    text = json.dumps(asdict(issue), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def worktree_tree(
    project_root: Path, exclude: Path | None = None
) -> str:
    """Tree-Hash wie nach ``git add -A``, ohne den Index zu ändern."""
    excluded = [_EXCLUDED, *_exclude_pathspec(project_root, exclude)]
    with tempfile.TemporaryDirectory(prefix="ki-dev-stand-") as tmp:
        env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(project_root, env, "add", "-A", "--", ".", *excluded)
        return _git(project_root, env, "write-tree").strip()


def _exclude_pathspec(
    project_root: Path, path: Path | None
) -> list[str]:
    """Eine Datei im Projekt als Ausschluss; außerhalb zählt sie ohnehin
    nicht zum Arbeitsbaum."""
    if path is None:
        return []
    try:
        relative = path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return []
    return [f":(exclude,literal){relative.as_posix()}"]


def _inside_worktree(project_root: Path) -> bool:
    code, stdout = _run_git(
        project_root, {}, "rev-parse", "--is-inside-work-tree"
    )
    return code == 0 and stdout.strip() == "true"


def _git(project_root: Path, env: dict[str, str], *args: str) -> str:
    code, stdout = _run_git(project_root, env, *args)
    if code != 0:
        # Feste Ursache statt Rohausgabe: git nennt Pfade des Projekts.
        raise StandError(f"git {args[0]} endete mit Exit-Code {code}")
    return stdout


def _run_git(
    project_root: Path, env: dict[str, str], *args: str
) -> tuple[int, str]:
    try:
        command = local["git"][args].with_env(**env)
    except CommandNotFound:
        raise StandError("git wurde nicht gefunden") from None
    try:
        proc = command.popen(cwd=project_root)
        code, stdout, _stderr = run_proc(proc, None, GIT_TIMEOUT_S)
    except ProcessTimedOut:
        raise StandError(
            f"git antwortete nicht innerhalb von {GIT_TIMEOUT_S} s"
        ) from None
    except FileNotFoundError:
        raise StandError("git wurde nicht gefunden") from None
    return code, stdout
