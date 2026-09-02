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
    try:
        commit = json.loads(out)["commit"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise DeltaCommandError(
            f"bd vc status lieferte kein commit-Feld: {out!r}"
        ) from exc
    return VcsRef(ChangeMedium.BEADS, str(commit))


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
    try:
        entries = json.loads(out)
    except json.JSONDecodeError as exc:
        raise DeltaCommandError(
            f"bd diff --json war kein JSON: {out!r}"
        ) from exc
    if isinstance(entries, dict) and "error" in entries:
        raise DeltaCommandError(f"bd diff meldete: {entries['error']}")
    return tuple(
        BeadsIssueChange(
            issue_id=str(entry["IssueID"]),
            change_type=str(entry["DiffType"]),
        )
        for entry in entries
    )


def _bd(repo: Path, *args: str) -> str:
    argv = ["bd", "-C", str(repo), *args]
    return run_command(argv).require_success()
