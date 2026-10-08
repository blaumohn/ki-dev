"""Reale, konfigurierbare Nachweiserfassung fuer eine Bau-Runde."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from ki_dev.adapter.contract import (
    RunTask,
    WorkReport,
)
from ki_dev.deltas import (
    ChangeMedium,
    CheckOutcome,
    ControllerContext,
    MediaRefs,
    RoundStatus,
    VcsRef,
    build_run_delta,
    build_step_delta,
    capture_media_refs,
    checkpoint_step_result,
)


@dataclass(frozen=True)
class CheckCommand:
    name: str
    argv: tuple[str, ...]
    timeout_s: float = 600.0

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("CheckCommand.name darf nicht leer sein")
        if not self.argv or any(not item for item in self.argv):
            raise ValueError("CheckCommand.argv darf nicht leer sein")
        if self.timeout_s <= 0:
            raise ValueError("CheckCommand.timeout_s muss positiv sein")


@dataclass(frozen=True)
class RepositoryEvidenceCollector:
    """Checkpointet Git und liest danach Git-/Beads-Deltas und Tests."""

    checks: tuple[CheckCommand, ...] = ()
    round_limit: int = 6

    def prepare(self, task: RunTask, round_id: int) -> object:
        del round_id
        _require_clean_worktree(task.workdir)
        return _encode_refs(capture_media_refs(task.workdir))

    def collect(
        self,
        task: RunTask,
        round_id: int,
        base: object,
        run_base: object,
        report: WorkReport,
    ) -> ControllerContext:
        del report
        step_base = _decode_refs(base)
        first_base = _decode_refs(run_base)
        result = checkpoint_step_result(
            task.workdir,
            message=f"ki-dev {task.run_id} Runde {round_id}",
        )
        return ControllerContext(
            task=task.task,
            step_delta=build_step_delta(
                task.workdir, step_base, result
            ),
            round_status=RoundStatus(round_id, self.round_limit),
            checks=tuple(
                _run_check(task, check) for check in self.checks
            ),
            run_delta=build_run_delta(task.workdir, first_base, result),
        )


def _run_check(task: RunTask, check: CheckCommand) -> CheckOutcome:
    """Fuehre einen Pruefauftrag im gebundenen Worktree aus.

    ``task.env`` ueberschreibt gezielt geerbte Umgebungsvariablen
    (z. B. eine fremde ``PYTHONPATH``), die den Kindprozess sonst
    stillschweigend gegen einen anderen Quellstand als
    ``task.workdir`` pruefen liessen.
    """
    try:
        completed = subprocess.run(
            check.argv,
            cwd=task.workdir,
            env={**os.environ, **task.env} if task.env else None,
            text=True,
            capture_output=True,
            timeout=check.timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CheckOutcome(check.name, False, str(exc))
    detail = (completed.stdout + completed.stderr).strip()
    return CheckOutcome(check.name, completed.returncode == 0, detail)


def _require_clean_worktree(repo: Path) -> None:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(f"Git-Arbeitsstand nicht pruefbar: {detail}")
    if completed.stdout:
        raise RuntimeError(
            "Bau-Worktree enthaelt vor dem Worker-Schritt fremde "
            "Aenderungen"
        )


def _encode_refs(refs: MediaRefs) -> dict[str, object]:
    return {
        "git": {
            "medium": refs.git.medium.value,
            "value": refs.git.value,
        },
        "beads": {
            "medium": refs.beads.medium.value,
            "value": refs.beads.value,
        },
    }


def _decode_refs(value: object) -> MediaRefs:
    if not isinstance(value, dict):
        raise TypeError("Referenzgrenze ist kein Objekt")
    git = cast(dict[str, str], value["git"])
    beads = cast(dict[str, str], value["beads"])
    return MediaRefs(
        VcsRef(ChangeMedium(git["medium"]), git["value"]),
        VcsRef(ChangeMedium(beads["medium"]), beads["value"]),
    )
