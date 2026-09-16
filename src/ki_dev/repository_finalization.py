"""Kontrollierte, wiederholbare Git-Finalisierung nach einem Review-PASS."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ki_dev.deltas import capture_beads_ref


class FinalizationFailure(RuntimeError):
    """Eine deterministische Abschlussbedingung ist nicht erfuellt."""


class Finalizer(Protocol):
    def freeze(
        self,
        *,
        source: Path,
        run_id: str,
        base_refs: dict[str, object],
        reviewed_refs: dict[str, object],
    ) -> dict[str, object]: ...

    def finalize_history(
        self, frozen: dict[str, object]
    ) -> dict[str, object]: ...

    def verify(
        self,
        frozen: dict[str, object],
        final: dict[str, object],
    ) -> dict[str, object]: ...

    def integrate(
        self,
        frozen: dict[str, object],
        final: dict[str, object],
    ) -> dict[str, object]: ...


@dataclass(frozen=True)
class RepositoryFinalizer:
    """Finalisiert einen isolierten Git-Arbeitszweig in einen Ziel-Worktree.

    Der kleine Schnitt unterstuetzt absichtlich nur dateibasierte Ergebnisse.
    Ein Git-Worktree isoliert die von Beads verwendete Dolt-Datenbank nicht;
    deshalb darf sich deren Referenz waehrend des Laufs nicht geaendert haben.
    """

    target_workdir: Path
    target_ref: str
    commit_message: str
    data_mode: str = "file_proposal"

    def __post_init__(self) -> None:
        if self.data_mode != "file_proposal":
            raise ValueError(
                "nur data_mode='file_proposal' wird unterstuetzt; direkte "
                "Beads-/Dolt-Schreibauftraege brauchen einen isolierten, "
                "versionierten DB-Arbeitsstand"
            )
        if not self.target_ref.startswith("refs/heads/"):
            raise ValueError("target_ref muss mit refs/heads/ beginnen")
        if not self.commit_message.strip():
            raise ValueError("commit_message darf nicht leer sein")

    def freeze(
        self,
        *,
        source: Path,
        run_id: str,
        base_refs: dict[str, object],
        reviewed_refs: dict[str, object],
    ) -> dict[str, object]:
        base_git = _ref_value(base_refs, "git")
        reviewed_git = _ref_value(reviewed_refs, "git")
        base_beads = _ref_value(base_refs, "beads")
        reviewed_beads = _ref_value(reviewed_refs, "beads")
        if base_beads != reviewed_beads:
            raise FinalizationFailure(
                "direkte Beads-/Dolt-Aenderungen werden in diesem Schnitt "
                "nicht uebernommen; einen dateibasierten Aenderungsvorschlag "
                "erzeugen"
            )
        _require_equal(
            _capture_beads_value(source),
            reviewed_beads,
            "Beads-/Dolt-Stand ist nach dem Review gedriftet",
        )
        _require_clean(source, "gepruefter Arbeitsstand")
        _require_equal(
            _git(source, "rev-parse", "HEAD"),
            reviewed_git,
            "HEAD ist nicht mehr der vom Reviewer gepruefte Commit",
        )
        _git(source, "merge-base", "--is-ancestor", base_git, reviewed_git)
        reviewed_tree = _git(
            source, "rev-parse", f"{reviewed_git}^{{tree}}"
        )
        _require_same_repository(source, self.target_workdir)
        return {
            "run_id": run_id,
            "source_workdir": str(source.resolve()),
            "target_workdir": str(self.target_workdir.resolve()),
            "target_ref": self.target_ref,
            "base_commit": base_git,
            "reviewed_commit": reviewed_git,
            "reviewed_tree": reviewed_tree,
            "base_beads_commit": base_beads,
            "reviewed_beads_commit": reviewed_beads,
            "data_mode": self.data_mode,
        }

    def finalize_history(
        self, frozen: dict[str, object]
    ) -> dict[str, object]:
        source = Path(_text(frozen, "source_workdir"))
        reviewed = _text(frozen, "reviewed_commit")
        timestamp = _git(source, "show", "-s", "--format=%ct", reviewed)
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "ki-dev",
            "GIT_AUTHOR_EMAIL": "ki-dev@example.invalid",
            "GIT_COMMITTER_NAME": "ki-dev",
            "GIT_COMMITTER_EMAIL": "ki-dev@example.invalid",
            "GIT_AUTHOR_DATE": f"{timestamp} +0000",
            "GIT_COMMITTER_DATE": f"{timestamp} +0000",
        }
        final_commit = _git(
            source,
            "commit-tree",
            _text(frozen, "reviewed_tree"),
            "-p",
            _text(frozen, "base_commit"),
            "-m",
            self.commit_message,
            env=env,
        )
        return {"final_commit": final_commit}

    def verify(
        self,
        frozen: dict[str, object],
        final: dict[str, object],
    ) -> dict[str, object]:
        try:
            source = Path(_text(frozen, "source_workdir"))
            target = Path(_text(frozen, "target_workdir"))
            final_commit = _text(final, "final_commit")
            _require_clean(source, "gepruefter Arbeitsstand")
            _require_clean(target, "Zielarbeitsstand")
            _require_equal(
                _git(source, "rev-parse", "HEAD"),
                _text(frozen, "reviewed_commit"),
                "gepruefter Arbeitszweig ist nach PASS gedriftet",
            )
            _require_equal(
                _capture_beads_value(source),
                _text(frozen, "reviewed_beads_commit"),
                "Beads-/Dolt-Stand ist nach PASS gedriftet",
            )
            _require_equal(
                _git(source, "rev-parse", f"{final_commit}^{{tree}}"),
                _text(frozen, "reviewed_tree"),
                "finaler Baum weicht vom geprueften Baum ab",
            )
            _require_target_ref(target, _text(frozen, "target_ref"))
            target_head = _git(target, "rev-parse", "HEAD")
            allowed = {
                _text(frozen, "base_commit"),
                final_commit,
            }
            if target_head not in allowed:
                raise FinalizationFailure(
                    "Zielreferenz ist seit Laufbeginn gedriftet"
                )
        except FinalizationFailure as exc:
            return {"ok": False, "detail": str(exc)}
        return {"ok": True, "detail": "Baum und Zielreferenz stimmen"}

    def integrate(
        self,
        frozen: dict[str, object],
        final: dict[str, object],
    ) -> dict[str, object]:
        verified = self.verify(frozen, final)
        if not verified["ok"]:
            return verified
        target = Path(_text(frozen, "target_workdir"))
        final_commit = _text(final, "final_commit")
        if _git(target, "rev-parse", "HEAD") != final_commit:
            try:
                _git(target, "merge", "--ff-only", final_commit)
            except FinalizationFailure as exc:
                return {"ok": False, "detail": str(exc)}
        try:
            _require_equal(
                _git(target, "rev-parse", "HEAD"),
                final_commit,
                "Fast-forward hat nicht den finalen Commit erreicht",
            )
            _require_equal(
                _git(target, "rev-parse", "HEAD^{tree}"),
                _text(frozen, "reviewed_tree"),
                "integrierter Baum weicht vom geprueften Baum ab",
            )
            _require_clean(target, "integrierter Zielarbeitsstand")
        except FinalizationFailure as exc:
            return {"ok": False, "detail": str(exc)}
        return {"ok": True, "detail": "Fast-forward integriert"}


@dataclass
class StaticFinalizer:
    """Deterministischer Finalizer fuer Laufzeittests ohne Git-Wirkung."""

    fail_verify: bool = False
    fail_integrate: bool = False

    def freeze(self, **kwargs: object) -> dict[str, object]:
        return {"run_id": kwargs["run_id"], "reviewed_tree": "tree-1"}

    def finalize_history(
        self, frozen: dict[str, object]
    ) -> dict[str, object]:
        del frozen
        return {"final_commit": "final-1"}

    def verify(
        self,
        frozen: dict[str, object],
        final: dict[str, object],
    ) -> dict[str, object]:
        del frozen, final
        return {"ok": not self.fail_verify, "detail": "fake verify"}

    def integrate(
        self,
        frozen: dict[str, object],
        final: dict[str, object],
    ) -> dict[str, object]:
        del frozen, final
        return {"ok": not self.fail_integrate, "detail": "fake integrate"}


def _ref_value(refs: dict[str, object], medium: str) -> str:
    item = refs.get(medium)
    if not isinstance(item, dict):
        raise FinalizationFailure(f"{medium}-Referenz fehlt")
    value = item.get("value")
    if not isinstance(value, str) or not value:
        raise FinalizationFailure(f"{medium}-Referenz ist ungueltig")
    return value


def _capture_beads_value(repo: Path) -> str:
    return capture_beads_ref(repo).value


def _text(value: dict[str, object], name: str) -> str:
    item = value.get(name)
    if not isinstance(item, str) or not item:
        raise FinalizationFailure(f"Finalisierungsnachweis ohne {name}")
    return item


def _require_clean(repo: Path, label: str) -> None:
    if _git(repo, "status", "--porcelain=v1", "--untracked-files=all"):
        raise FinalizationFailure(f"{label} enthaelt fremde Aenderungen")


def _require_target_ref(repo: Path, expected: str) -> None:
    actual = _git(repo, "symbolic-ref", "-q", "HEAD")
    _require_equal(actual, expected, "Ziel-Worktree steht auf fremder Referenz")


def _require_same_repository(source: Path, target: Path) -> None:
    args = ("rev-parse", "--path-format=absolute", "--git-common-dir")
    source_common = _git(source, *args)
    target_common = _git(target, *args)
    _require_equal(
        str(Path(source_common).resolve()),
        str(Path(target_common).resolve()),
        "Quell- und Ziel-Worktree gehoeren nicht zum selben Repository",
    )


def _require_equal(actual: str, expected: str, message: str) -> None:
    if actual != expected:
        raise FinalizationFailure(f"{message}: {actual} != {expected}")


def _git(
    repo: Path, *args: str, env: dict[str, str] | None = None
) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise FinalizationFailure(
            f"Git-Aufruf fehlgeschlagen ({' '.join(args)}): {detail}"
        )
    return completed.stdout.strip()
