"""Test-Tor über die öffentliche CLI: ein Review-PASS überstimmt keine
roten Tests (ki-dev-ablauf-ek1).

Eigene kleine Fixture: Ziel-Repo ``main`` mit ``add.py`` und
``test_add.py``, Arbeits-Worktree ``arbeit`` mit Beads-Projekt, Profil
mit ``[[tests]]``. Worker und Review sind ``mock``, das Review spricht
immer PASS; die Sandbox ersetzt die Anbieter durch Attrappen.
Beobachtet wird nur, was ``ki-dev -f implement`` ausgibt und ins
Laufverzeichnis schreibt, und der Ziel-Ref.

``bd`` ist Voraussetzung: fehlt es, scheitert der Test, statt still
übersprungen zu werden.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from tests.spec.sandbox import Sandbox

ORACLE = (
    sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
    "test_add.py",
)
TEST_ADD = """\
from add import add


def test_add():
    assert add(2, 3) == 5
    assert add(-1, 1) == 0
"""
PROFILE = """\
workdir = "{workdir}"
access_profile = "write"

[[tests]]
name = "pytest"
argv = {oracle}

[finalization]
target_workdir = "{target}"
target_ref = "refs/heads/main"
commit_message = "Geprüfter Abschluss"
data_mode = "file_proposal"

[worker]
executor = "mock"

[review]
executor = "mock"
answers = ["PASS"]
"""


def _implement(sandbox: Sandbox, operator: str) -> dict:
    """Lauf mit Review-PASS über die öffentliche CLI, ``add`` als
    ``a <operator> b``; Ergebnis samt Ziel-Ref vorher/nachher,
    Ereignissen und Prüfnachweisen."""
    sandbox.write(".gitignore", ".beads.gate.lock\n__pycache__/\n")
    sandbox.write(
        "add.py", f"def add(a, b):\n    return a {operator} b\n"
    )
    sandbox.write("test_add.py", TEST_ADD)
    sandbox.commit("start")
    work = sandbox.base / "arbeit"
    runs = sandbox.base / "runs"
    sandbox.prepare(
        ["git", "-C", sandbox.repo, "worktree", "add", "-q", "-b",
         "arbeit", work]
    )
    sandbox.prepare(
        ["bd", "init", "--prefix", "demo", "--skip-agents",
         "--skip-hooks", "--stealth"],
        cwd=work,
    )
    bead = sandbox.prepare(
        ["bd", "create", "add korrigieren",
         "--description", "add() soll addieren",
         "--design", "nur add.py ändern",
         "--acceptance", "add(2,3)==5 und add(-1,1)==0",
         "--silent"],
        cwd=work,
    ).stdout.strip()
    profile = sandbox.base / "profil.toml"
    profile.write_text(
        PROFILE.format(
            workdir=work,
            target=sandbox.repo,
            oracle=json.dumps(list(ORACLE)),
        )
    )
    before = _target_ref(sandbox)
    outcome = sandbox.run(
        ["ki-dev", "-f", "implement", bead, "--profile", profile,
         "--run-id", "r", "--runs-dir", runs],
        cwd=work,
    )
    assert outcome.code == 0, outcome.stderr
    run = runs / "r"
    return {
        "result": json.loads(outcome.stdout),
        "before": before,
        "after": _target_ref(sandbox),
        "events": [
            json.loads(line)
            for line in (run / "events.jsonl").read_text().splitlines()
        ],
        "checks": [
            check
            for path in sorted((run / "artifacts").glob("*-evidence-*"))
            for check in _checks(path)
        ],
    }


def _checks(evidence: Path) -> list[dict]:
    return json.loads(evidence.read_text())["context"]["checks"]


def _target_ref(sandbox: Sandbox) -> str:
    return sandbox.prepare(
        ["git", "-C", sandbox.repo, "rev-parse", "refs/heads/main"]
    ).stdout.strip()


def _assert_review_pass_after_mock_roles(events: list[dict]) -> None:
    """Worker und Review liefen getrennt mit ``mock``; das Review
    sprach PASS."""
    worker = [
        e for e in events
        if e["event"] == "worker_completed" and e["adapter"] == "mock"
    ]
    review = [
        e for e in events
        if e["state"] == "controller_step" and e["event"] == "PASS"
    ]
    assert worker, "kein Worker-Turn mit mock beobachtet"
    assert review, "kein Review-PASS beobachtet"
    assert worker[0]["actor"] != review[0]["actor"]


def test_green_tests_and_review_pass_integrate(sandbox):
    """Tests grün + Review PASS -> Commit auf dem Ziel-Ref."""
    run = _implement(sandbox, "+")
    _assert_review_pass_after_mock_roles(run["events"])
    assert [c["passed"] for c in run["checks"]] == [True]
    assert run["result"]["status"] == "passed", run["result"]
    assert run["after"] != run["before"]


def test_red_tests_and_review_pass_do_not_integrate(sandbox):
    """Tests rot + Review PASS -> Halt für den Menschen, kein Commit
    auf dem Ziel-Ref; die Meldung nennt Ursache und rote Prüfung."""
    run = _implement(sandbox, "-")
    _assert_review_pass_after_mock_roles(run["events"])
    assert [c["passed"] for c in run["checks"]] == [False]
    assert "1 failed" in run["checks"][0]["detail"]
    assert run["result"]["status"] != "passed", run["result"]
    assert run["after"] == run["before"]
    detail = run["result"]["detail"]
    assert detail.startswith("checks_failed: "), detail
    assert "pytest" in detail
