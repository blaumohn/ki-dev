"""``bd``-/Dolt-Referenzgrenzen und -Deltas ueber Dolt-Versionierung.

Beads versioniert seinen Bestand selbst in Dolt (Anlage A). ``ki-dev``
verwendet ausschliesslich diese vorhandene Versionierung und baut keine
eigene Snapshot-, Normalisierungs- oder Vergleichslogik. Der Export
``.beads/issues.jsonl`` ist nur passiv und niemals die
Versionswahrheit.

Reale Schnittstelle der unterstuetzten Beads-Version:

* Versionsgrenze erfassen: ``bd vc status --json`` -> Feld ``commit``
* Delta bilden: ``bd diff FROM_REF TO_REF`` (Text und ``--json``)

``bd vc diff`` existiert in dieser Version nicht und wird nicht
vorausgesetzt.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .command import DeltaCommandError, run_command
from .contract import (
    BeadsDelta,
    BeadsIssueChange,
    ChangeMedium,
    RefBoundary,
    VcsRef,
)

SUPPORTED_BD_VERSION = "1.2.2"
BD_DIFF_INTERFACE = ("bd", "diff", "FROM_REF", "TO_REF")

_VERSION = re.compile(r"\bbd version (\d+\.\d+\.\d+)")
_NO_CHANGES = "No changes between"


def installed_bd_version(bd: str = "bd") -> str:
    """Lies die installierte ``bd``-Version aus ``bd version``."""
    out = run_command([bd, "version"]).require_success()
    match = _VERSION.search(out)
    if match is None:
        raise DeltaCommandError(f"bd-Version nicht erkennbar: {out!r}")
    return match.group(1)


def verify_bd_version(bd: str = "bd") -> None:
    """Bestehe nur bei exakt der unterstuetzten ``bd``-Version."""
    found = installed_bd_version(bd)
    if found != SUPPORTED_BD_VERSION:
        raise DeltaCommandError(
            f"bd {SUPPORTED_BD_VERSION} erwartet, gefunden {found}"
        )


def capture_beads_ref(repo: Path) -> VcsRef:
    """Erfasse den aktuellen Dolt-Commit der Beads-Datenbank."""
    out = _bd(repo, "vc", "status", "--json")
    return VcsRef(ChangeMedium.BEADS, _commit_field(out))


def _commit_field(raw: str) -> str:
    payload = _load_json(raw, "bd vc status --json")
    if not isinstance(payload, dict):
        raise DeltaCommandError(
            f"bd vc status --json war kein Objekt: {raw!r}"
        )
    commit = payload.get("commit")
    if not isinstance(commit, str) or not commit.strip():
        raise DeltaCommandError(
            f"bd vc status ohne gueltiges commit-Feld: {raw!r}"
        )
    return commit


def build_beads_delta(repo: Path, boundary: RefBoundary) -> BeadsDelta:
    """Bilde den ``bd``-/Dolt-Delta zwischen den beiden Referenzen."""
    if boundary.medium is not ChangeMedium.BEADS:
        raise ValueError("RefBoundary ist nicht beads")
    base, result = boundary.base.value, boundary.result.value
    issues = _diff_issues(repo, base, result)
    summary = _bd(repo, "diff", base, result).strip()
    return BeadsDelta(boundary=boundary, issues=issues, summary=summary)


def _diff_issues(
    repo: Path,
    base: str,
    result: str,
) -> tuple[BeadsIssueChange, ...]:
    out = _bd(repo, "diff", base, result, "--json").strip()
    if not out or out.startswith(_NO_CHANGES):
        return ()
    entries = _load_json(out, "bd diff --json")
    if isinstance(entries, dict) and "error" in entries:
        raise DeltaCommandError(f"bd diff meldete: {entries['error']}")
    if not isinstance(entries, list):
        raise DeltaCommandError(
            f"bd diff --json war keine Liste: {out!r}"
        )
    return tuple(_issue_change(entry) for entry in entries)


def _issue_change(entry: object) -> BeadsIssueChange:
    if not isinstance(entry, dict):
        raise DeltaCommandError(
            f"bd diff --json Eintrag ist kein Objekt: {entry!r}"
        )
    issue_id = entry.get("IssueID")
    change_type = entry.get("DiffType")
    if not isinstance(issue_id, str) or not isinstance(
        change_type, str
    ):
        raise DeltaCommandError(
            f"bd diff --json Eintrag ohne Pflichtfelder: {entry!r}"
        )
    return BeadsIssueChange(issue_id=issue_id, change_type=change_type)


def _load_json(raw: str, label: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DeltaCommandError(
            f"{label} war kein JSON: {raw!r}"
        ) from exc


def _bd(repo: Path, *args: str) -> str:
    argv = ["bd", "-C", str(repo), *args]
    return run_command(argv).require_success()
