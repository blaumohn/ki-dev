"""Anforderungskatalog, Einordnung der pytest-Ergebnisse und
Ergebnisbericht.

Der Katalog (TOML) beschreibt, was gelten soll; Tests verweisen per
Marker auf seine IDs. Der Bericht führt beides zusammen, ohne einen
Status umzudeuten: ``passed`` nur bei bestandenem Testaufruf,
``failed`` bei inhaltlicher Verletzung (``AssertionError``),
``not-run`` bei früher Blockade, Infrastrukturfehler oder Auslassung,
``missing-test`` für Anforderungen ohne Test. Kontrollen prüfen den
Testprüfer und werden getrennt von den Produktanforderungen gezeigt.
"""

from __future__ import annotations

import hashlib
import json
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path

from plumbum import local

from tests.spec.evidence import Blocked
from tests.spec.schema import problems

LEVELS = {
    "architecture": "Architektur",
    "feature": "Feature",
    "actual": "Ist",
}
CHECKER = {
    "accepted": "abgenommen",
    "rejected": "nicht abgenommen",
    "no-control": "keine Kontrolle",
}
SCAFFOLD = "scaffold"
REPORT_FILES = ("report.json", "report.md")


class SpecError(Exception):
    """Katalog, Marker oder Bericht verletzen den Vertrag."""


@dataclass(frozen=True)
class Result:
    status: str
    blocked: dict | None = None
    message: str | None = None


def load_catalog(path: Path) -> dict[str, dict]:
    data = tomllib.loads(path.read_text())
    errors = problems("catalog", data)
    if errors:
        raise SpecError(f"{path}: " + "; ".join(errors))
    return data["requirement"]


def classify(report, excinfo) -> Result | None:
    """Ergebnis einer pytest-Phase; ``None``, wenn sie nichts ändert."""
    if report.passed:
        return Result("passed") if report.when == "call" else None
    if report.skipped:
        return Result("not-run", message=_skip_reason(report))
    error = excinfo.value
    if isinstance(error, Blocked):
        return Result(
            "not-run",
            blocked={"stage": error.stage, "detail": error.detail},
        )
    if report.when == "call" and isinstance(error, AssertionError):
        return Result("failed", message=_first_line(excinfo))
    return Result(
        "not-run",
        blocked={
            "stage": "infrastructure",
            "detail": f"{report.when}: {_first_line(excinfo)}",
        },
    )


def merge(current: Result | None, new: Result | None) -> Result | None:
    """Spätere Phase ersetzt nur ein bisheriges ``passed``."""
    if new is None:
        return current
    if current is None or current.status == "passed":
        return new
    return current


def requirement_row(
    rid, entry, nodeid, result, evidence, checker, revision
):
    return {
        "id": rid,
        "level": entry["level"],
        "requirement": entry["text"],
        "command": "; ".join(evidence.commands) if evidence else None,
        "rerun": _rerun(nodeid),
        "revision": revision,
        "expected": entry["expected"],
        "observed": _observed(result, evidence),
        "status": _requirement_status(nodeid, result),
        "blocked": result.blocked if result else None,
        "checker": checker,
        "bead": entry["bead"],
    }


def control_row(nodeid, marker, description, result, evidence):
    return {
        "id": nodeid,
        "target": marker["target"],
        "expect": marker["expect"],
        "description": description,
        "status": result.status if result else "not-run",
        "observed": _observed(result, evidence),
    }


def checker_state(statuses: list[str]) -> str:
    if not statuses:
        return "no-control"
    if all(status == "passed" for status in statuses):
        return "accepted"
    return "rejected"


def read_revision(root: Path) -> dict:
    git = local["git"]
    code, commit, _ = git.run(
        args=["-C", root, "rev-parse", "--short", "HEAD"],
        retcode=None,
        timeout=10,
    )
    if code != 0:
        return {"commit": None, "dirty": None, "worktree": None}
    status = git.run(
        args=["-C", root, "status", "--porcelain"],
        retcode=0,
        timeout=30,
    )[1]
    dirty = bool(status.strip())
    return {
        "commit": commit.strip(),
        "dirty": dirty,
        "worktree": worktree_digest(root) if dirty else None,
    }


def worktree_digest(root: Path) -> str:
    """SHA-256 über Diff gegen HEAD und unversionierte Dateien: gleicher
    Commit mit anderem Arbeitsstand ergibt einen anderen Wert."""
    git = local["git"]
    digest = hashlib.sha256()
    diff = git.run(
        args=["-C", root, "diff", "--binary", "HEAD"],
        retcode=0,
        timeout=60,
    )[1]
    digest.update(diff.encode())
    untracked = git.run(
        args=["-C", root, "ls-files", "-z", "--others",
              "--exclude-standard"],
        retcode=0,
        timeout=60,
    )[1]
    for name in sorted(filter(None, untracked.split("\0"))):
        digest.update(name.encode() + b"\0")
        digest.update((root / name).read_bytes())
    return digest.hexdigest()


def all_passed(report: dict) -> bool:
    rows = report["requirements"] + report["controls"]
    return all(row["status"] == "passed" for row in rows)


def write_report(directory: Path, report: dict) -> None:
    errors = problems("report", report)
    if errors:
        raise SpecError("Ergebnisbericht: " + "; ".join(errors))
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    (directory / "report.md").write_text(render(report))


def clear_report(directory: Path) -> None:
    """Bericht eines früheren Laufs entfernen, bevor dieser beginnt."""
    for name in REPORT_FILES:
        (directory / name).unlink(missing_ok=True)


def write_abort(directory: Path, exitstatus, revision: dict) -> None:
    """Abgebrochener Lauf: kein report.json, nur eine Notiz."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.md").write_text(
        "# Anforderungstests: abgebrochen\n\n"
        f"Stand: {_revision_text(revision)}\n\n"
        f"Lauf abgebrochen ({exitstatus!s}), etwa durch Sammel-, "
        "Import- oder Katalogfehler. Es gibt kein Ergebnis; "
        "kein Status gilt als geprüft.\n"
    )


def render(report: dict) -> str:
    lines = [
        "# Anforderungstests: Ergebnis",
        "",
        f"Stand: {_revision_text(report['revision'])}; "
        f"erzeugt {report['generated']}",
        f"Aufruf: `{report['invocation']}`",
        "",
        *_controls_section(report["controls"]),
        "",
        *_requirements_section(report["requirements"]),
        "",
        *_actual_section(report["requirements"]),
    ]
    return "\n".join(lines) + "\n"


def _controls_section(rows: list[dict]) -> list[str]:
    scaffold = [r for r in rows if r["target"] == SCAFFOLD]
    passed = sum(r["status"] == "passed" for r in scaffold)
    accepted = "ja" if scaffold and passed == len(scaffold) else "nein"
    return [
        "## Testprüfer (Kontrollen)",
        "",
        f"Prüfgerüst abgenommen: {accepted} "
        f"({passed} von {len(scaffold)} Gerüstkontrollen bestanden)",
        "",
        "| Kontrolle | Ziel | Fall ergibt | Kontrolle | Beobachtet |",
        "|---|---|---|---|---|",
        *(
            _table_row(
                r["description"], r["target"], r["expect"],
                r["status"], r["observed"],
            )
            for r in rows
        ),
    ]


def _requirements_section(rows: list[dict]) -> list[str]:
    target = [r for r in rows if r["level"] != "actual"]
    return [
        "## Produktanforderungen",
        "",
        f"Erfüllt: {_counts(target)}",
        "",
        *_row_table(target),
    ]


def _actual_section(rows: list[dict]) -> list[str]:
    actual = [r for r in rows if r["level"] == "actual"]
    return [
        "## Ist-Beobachtungen (keine Anforderung)",
        "",
        f"Bestätigt: {_counts(actual)}",
        "",
        *_row_table(actual),
    ]


def _counts(rows: list[dict]) -> str:
    passed = sum(r["status"] == "passed" for r in rows)
    counts = ", ".join(
        f"{status} {sum(r['status'] == status for r in rows)}"
        for status in ("passed", "failed", "not-run", "missing-test")
    )
    return f"{passed} von {len(rows)} ({counts})"


def _row_table(rows: list[dict]) -> list[str]:
    return [
        "| ID | Ebene | Aussage | Befehl | Erwartet | Beobachtet "
        "| Testprüfer | Status | Bead |",
        "|---|---|---|---|---|---|---|---|---|",
        *_empty_hint(rows),
        *(
            _table_row(
                r["id"], LEVELS[r["level"]], r["requirement"],
                r["command"], r["expected"], _observed_text(r),
                CHECKER[r["checker"]], r["status"], r["bead"],
            )
            for r in rows
        ),
    ]


def _empty_hint(rows: list[dict]) -> list[str]:
    if rows:
        return []
    return ["| – | – | keine Einträge im Katalog "
            "| – | – | – | – | – | – |"]


def _requirement_status(nodeid, result) -> str:
    if nodeid is None:
        return "missing-test"
    return result.status if result else "not-run"


def _observed(result, evidence) -> str | None:
    notes = evidence.notes if evidence else []
    message = result.message if result else None
    return "; ".join(filter(None, [*notes, message])) or None


def _observed_text(row: dict) -> str | None:
    blocked = row["blocked"]
    if blocked is None:
        return row["observed"]
    prefix = f"blockiert ({blocked['stage']}): {blocked['detail']}"
    return "; ".join(filter(None, [prefix, row["observed"]]))


def _rerun(nodeid) -> str | None:
    if nodeid is None:
        return None
    return f"pytest --spec {shlex.quote(nodeid)}"


def _revision_text(revision: dict) -> str:
    if revision["commit"] is None:
        return "unbekannt (kein Git-Arbeitsstand)"
    if revision["dirty"]:
        return (
            f"{revision['commit']} mit nicht committeten Änderungen "
            f"(Arbeitsstand sha256:{revision['worktree']})"
        )
    return revision["commit"]


def _table_row(*cells) -> str:
    text = (_cell(cell) for cell in cells)
    return "| " + " | ".join(text) + " |"


def _cell(value) -> str:
    if value is None:
        return "–"
    return " ".join(str(value).split()).replace("|", "\\|")


def _skip_reason(report) -> str:
    longrepr = report.longrepr
    if isinstance(longrepr, tuple):
        reason = longrepr[2].removeprefix("Skipped: ")
        return f"ausgelassen: {reason}"
    return "ausgelassen"


def _first_line(excinfo) -> str:
    return excinfo.exconly().splitlines()[0][:300]
