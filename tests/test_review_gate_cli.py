"""Stufe 2 über die öffentliche CLI: ein Review-PASS darf rote Tests
nicht überstimmen (ki-dev-ablauf-4l9).

Eigene kleine Fixture: Ziel-Repo ``main`` mit ``add.py`` und
``test_add.py``, Arbeits-Worktree ``arbeit`` mit Beads-Projekt, Profil
mit ``[[tests]]``. Worker und Review sind ``mock``; die Sandbox ersetzt
die Anbieter durch Attrappen, ein Start lässt den Test scheitern.
Beobachtet wird nur, was ``ki-dev -f implement`` ausgibt und ins
Laufverzeichnis schreibt, und der Ziel-Ref.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from plumbum import CommandNotFound, local

from tests.spec.sandbox import Sandbox

PRODUCT_BEAD = "ki-dev-ablauf-ek1"
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


def _bd_available() -> bool:
    try:
        local["bd"]
    except CommandNotFound:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _bd_available(), reason="bd lokal nicht installiert"
)


class IntegratedDespiteRedTests(AssertionError):
    """Der Lauf hat trotz roter Tests auf den Ziel-Ref integriert."""


def _example(sandbox: Sandbox, operator: str) -> None:
    """Ziel-Repo mit ``add`` als ``a <operator> b`` und festen Tests."""
    sandbox.write(".gitignore", ".beads.gate.lock\n__pycache__/\n")
    sandbox.write(
        "add.py", f"def add(a, b):\n    return a {operator} b\n"
    )
    sandbox.write("test_add.py", TEST_ADD)
    sandbox.commit("start")


def _implement(sandbox: Sandbox, operator: str) -> dict:
    """Lauf mit Review-PASS über die öffentliche CLI; Ergebnis samt
    Ziel-Ref vorher/nachher, Ereignissen und Prüfnachweisen."""
    _example(sandbox, operator)
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


def _failed_by_assertion(check: dict) -> bool:
    """Der Prüfnachweis belegt einen echten Testfehlschlag, keine frühe
    Blockade wie Collection-Fehler, Timeout oder Startfehler."""
    detail = check["detail"]
    return (
        not check["passed"]
        and re.search(r"^FAILED test_add\.py::test_add\b", detail, re.M)
        is not None
        and re.search(r"^1 failed in ", detail, re.M) is not None
    )


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


@pytest.mark.parametrize(("operator", "expected"), [("-", 1), ("+", 0)])
def test_oracle_tells_red_from_green(sandbox, operator, expected):
    """Kontrolle des Orakels: a-b ist rot (pytest-Exitcode 1, also ein
    Fehlschlag statt Collection- oder Aufruffehler), a+b grün."""
    _example(sandbox, operator)
    outcome = sandbox.run(ORACLE)
    assert outcome.code == expected, outcome.stdout


def test_green_tests_and_review_pass_integrate(sandbox):
    """Kontrolle des Testprüfers: Integration ist beobachtbar, ein
    ausbleibender Commit im roten Fall also kein Zufall der Fixture."""
    run = _implement(sandbox, "+")
    _assert_review_pass_after_mock_roles(run["events"])
    assert [c["passed"] for c in run["checks"]] == [True]
    assert run["result"]["status"] == "passed", run["result"]
    assert run["after"] != run["before"]


@pytest.mark.xfail(
    strict=True,
    raises=IntegratedDespiteRedTests,
    reason=f"{PRODUCT_BEAD}: Review-PASS integriert trotz roter Tests",
)
def test_red_tests_and_review_pass_do_not_integrate(sandbox):
    """Tests rot + Review PASS -> kein Commit auf dem Ziel-Ref."""
    run = _implement(sandbox, "-")
    _assert_review_pass_after_mock_roles(run["events"])
    assert run["checks"], "keine Prüfung im Nachweis"
    checks = run["checks"]
    assert all(_failed_by_assertion(c) for c in checks), checks
    integrated = run["result"]["status"] == "passed"
    if integrated or run["after"] != run["before"]:
        raise IntegratedDespiteRedTests(
            f"{run['before'][:7]} -> {run['after'][:7]}: "
            f"{run['result']['detail']}"
        )
