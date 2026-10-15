"""Gerüstkontrollen: prüfen den Testprüfer, nicht das Produkt.

Ein innerer ``pytest --spec``-Lauf über bekannte Beispiele muss jeden
Fall richtig einordnen: erwartetes PASS, inhaltlicher Fehlschlag,
Infrastrukturfehler, frühe Blockade, Anbieterstart, Auslassung und
fehlender Test. Kein Beispiel ruft ki-dev oder ein Modell auf.
"""

from __future__ import annotations

import pytest
from plumbum import local

from tests.spec.inner import run_inner
from tests.spec.report import read_revision

ENTRY = """
[requirement.{rid}]
level = "{level}"
text = "Beispiel {rid}"
expected = "Einordnung {rid}"
bead = "ki-dev-ablauf-23r"
"""
SAMPLE_IDS = (
    "DEMO-PASS", "DEMO-FAIL", "DEMO-INFRA", "DEMO-BLOCKED",
    "DEMO-PROVIDER", "DEMO-SKIP", "DEMO-CRASH", "DEMO-MISSING",
)
SAMPLES = '''
import pytest
from tests.spec.evidence import Blocked

@pytest.mark.requirement("DEMO-PASS")
def test_pass(sandbox, evidence):
    sandbox.write("a.txt", "a\\n")
    sandbox.commit("start")
    outcome = sandbox.run(["git", "rev-parse", "--verify", "HEAD"])
    evidence.note(f"exit {outcome.code}")
    assert outcome.code == 0

@pytest.mark.requirement("DEMO-FAIL")
def test_fail(sandbox):
    outcome = sandbox.run(["git", "rev-parse", "--verify", "HEAD"])
    assert outcome.code == 0, f"exit {outcome.code} ohne Commit"

@pytest.mark.requirement("DEMO-INFRA")
def test_infra(sandbox):
    sandbox.run(["ki-dev-gibt-es-nicht", "--help"])

@pytest.mark.requirement("DEMO-BLOCKED")
def test_blocked(sandbox):
    outcome = sandbox.run(["git", "kein-befehl"])
    if outcome.code != 0:
        detail = f"git kein-befehl endet mit {outcome.code}"
        raise Blocked("cli", detail)
    raise AssertionError("Merkmal hinter der CLI")

@pytest.mark.requirement("DEMO-PROVIDER")
def test_provider(sandbox):
    sandbox.run(["claude", "-p", "hallo"])

@pytest.mark.requirement("DEMO-IST")
def test_actual():
    pass

@pytest.mark.requirement("DEMO-SKIP")
def test_skip():
    pytest.skip("Beispiel ausgelassen")

@pytest.mark.requirement("DEMO-CRASH")
def test_crash():
    raise KeyError("Prüfcode")

@pytest.mark.control(target="DEMO-FAIL", expect="failed")
def test_accepting_control():
    """Kontrolle besteht"""

@pytest.mark.control(target="DEMO-PASS", expect="passed")
def test_rejecting_control():
    """Kontrolle scheitert"""
    raise AssertionError("Prüfer erkennt den Fall nicht")

def test_plain():
    pass
'''
CONTRACT_SAMPLES = '''
import pytest

@pytest.mark.requirement("UNBEKANNT")
def test_unknown():
    pass

@pytest.mark.requirement("DEMO-PASS")
def test_first():
    pass

@pytest.mark.requirement("DEMO-PASS")
def test_second():
    pass

@pytest.mark.xfail
@pytest.mark.control(target="scaffold", expect="passed")
def test_xfail():
    pass

@pytest.mark.control(target="NIRGENDS", expect="grün")
def test_bad_control():
    pass
'''


def catalog(*ids, level="feature") -> str:
    return "".join(ENTRY.format(rid=rid, level=level) for rid in ids)


@pytest.fixture(scope="module")
def inner(tmp_path_factory):
    return run_inner(
        tmp_path_factory.mktemp("inner"),
        {
            "catalog.toml": catalog(*SAMPLE_IDS)
            + catalog("DEMO-IST", level="actual"),
            "test_samples.py": SAMPLES,
        },
        "--spec",
    )


@pytest.mark.control(target="scaffold", expect="passed")
def test_expected_pass(inner):
    """Erwartetes PASS: bestandener Aufruf ergibt passed mit Befehl"""
    row = inner.row("DEMO-PASS")
    assert row["status"] == "passed"
    assert row["blocked"] is None
    assert row["observed"] == "exit 0"
    assert row["command"] == "git rev-parse --verify HEAD"
    assert row["rerun"] == "pytest --spec test_samples.py::test_pass"


@pytest.mark.control(target="scaffold", expect="failed")
def test_expected_fail(inner):
    """Erwartetes FAIL: inhaltliche Verletzung ergibt failed"""
    row = inner.row("DEMO-FAIL")
    assert row["status"] == "failed"
    assert row["blocked"] is None
    assert "ohne Commit" in row["observed"]


@pytest.mark.control(target="scaffold", expect="not-run")
def test_infrastructure_error(inner):
    """Infrastrukturfehler: nicht startbarer Befehl ergibt not-run"""
    row = inner.row("DEMO-INFRA")
    assert row["status"] == "not-run"
    assert row["blocked"]["stage"] == "infrastructure"
    assert "ki-dev-gibt-es-nicht" in row["blocked"]["detail"]


@pytest.mark.control(target="scaffold", expect="not-run")
def test_early_blockade_differs_from_violation(inner):
    """Frühe CLI-Blockade: Merkmal nicht geprüft, kein failed"""
    row = inner.row("DEMO-BLOCKED")
    assert row["status"] == "not-run"
    assert row["blocked"] == {
        "stage": "cli",
        "detail": "git kein-befehl endet mit 1",
    }


@pytest.mark.control(target="scaffold", expect="failed")
def test_provider_start_fails(inner):
    """Anbieterstart im Standardlauf ergibt failed"""
    row = inner.row("DEMO-PROVIDER")
    assert row["status"] == "failed"
    assert "Anbieter im Standardlauf gestartet: claude -p hallo" in (
        row["observed"]
    )


@pytest.mark.control(target="scaffold", expect="not-run")
def test_skip_and_crash_are_not_passed(inner):
    """Auslassung und Fehler im Prüfcode ergeben not-run, nie passed"""
    skip = inner.row("DEMO-SKIP")
    crash = inner.row("DEMO-CRASH")
    assert (skip["status"], skip["blocked"]) == ("not-run", None)
    assert skip["observed"] == "ausgelassen: Beispiel ausgelassen"
    assert crash["status"] == "not-run"
    assert crash["blocked"]["stage"] == "infrastructure"
    assert crash["blocked"]["detail"].startswith("call: KeyError")


@pytest.mark.control(target="scaffold", expect="missing-test")
def test_requirement_without_test_is_missing(inner):
    """Anforderung ohne Test ergibt missing-test"""
    row = inner.row("DEMO-MISSING")
    assert row["status"] == "missing-test"
    assert (row["command"], row["rerun"]) == (None, None)


@pytest.mark.control(target="scaffold", expect="failed")
def test_checker_shown_apart_from_product(inner):
    """Testprüfer-Abnahme getrennt vom Produktstatus"""
    checker = {
        rid: (inner.row(rid)["checker"], inner.row(rid)["status"])
        for rid in ("DEMO-FAIL", "DEMO-PASS", "DEMO-INFRA")
    }
    assert checker == {
        "DEMO-FAIL": ("accepted", "failed"),
        "DEMO-PASS": ("rejected", "passed"),
        "DEMO-INFRA": ("no-control", "not-run"),
    }
    assert "## Testprüfer (Kontrollen)" in inner.output
    assert "## Produktanforderungen" in inner.output
    assert "Erfüllt: 1 von 8" in inner.output
    assert "## Ist-Beobachtungen (keine Anforderung)" in inner.output
    assert "Bestätigt: 1 von 1" in inner.output


@pytest.mark.control(target="scaffold", expect="failed")
def test_run_fails_and_deselects_plain_tests(inner):
    """Verletzung macht den Lauf rot; normale Tests sind abgewählt"""
    assert inner.code == pytest.ExitCode.TESTS_FAILED
    assert "1 deselected" in inner.output
    ids = {row["id"] for row in inner.report["controls"]}
    assert ids == {
        "test_samples.py::test_accepting_control",
        "test_samples.py::test_rejecting_control",
    }


@pytest.mark.control(target="scaffold", expect="passed")
def test_all_passed_run_is_green(tmp_path):
    """Nur wenn alles besteht, endet der Lauf grün"""
    run = run_inner(
        tmp_path,
        {
            "catalog.toml": catalog("DEMO-PASS"),
            "test_samples.py": """
                import pytest

                @pytest.mark.requirement("DEMO-PASS")
                def test_pass():
                    pass

                @pytest.mark.control(
                    target="DEMO-PASS", expect="passed"
                )
                def test_control():
                    pass
            """,
        },
        "--spec",
    )
    assert run.code == pytest.ExitCode.OK, run.output
    assert run.row("DEMO-PASS")["checker"] == "accepted"


@pytest.mark.control(target="scaffold", expect="not-run")
def test_contract_violations_stop_collection(tmp_path):
    """Unbekannte ID, Doppelung, xfail, falsche Kontrolle: Abbruch"""
    run = run_inner(
        tmp_path,
        {
            "catalog.toml": catalog("DEMO-PASS"),
            "test_samples.py": CONTRACT_SAMPLES,
        },
        "--spec",
    )
    assert run.code == pytest.ExitCode.USAGE_ERROR
    assert run.report is None
    for message in (
        "Anforderung 'UNBEKANNT' fehlt im Katalog",
        "Anforderung DEMO-PASS schon von test_samples.py::test_first",
        "test_samples.py::test_xfail: xfail verdeckt den Status",
        "Kontrollziel 'NIRGENDS' unbekannt",
        "expect 'grün' unbekannt",
    ):
        assert message in run.output


@pytest.mark.control(target="scaffold", expect="passed")
def test_sandbox_hides_credentials(sandbox, monkeypatch):
    """Sandbox: eigenes HOME, keine geerbten Zugangsdaten"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "geheim")
    monkeypatch.setenv("KI_DEV_TEST_LIVE", "1")
    outcome = sandbox.run(["sh", "-c", "env"])
    env = dict(
        line.split("=", 1) for line in outcome.stdout.splitlines()
    )
    assert env["HOME"] == str(sandbox.base / "home")
    assert "ANTHROPIC_API_KEY" not in env
    assert "KI_DEV_TEST_LIVE" not in env
    assert env["PATH"].split(":")[0] == str(sandbox.base / "bin")


GREEN = """
import pytest

@pytest.mark.requirement("DEMO-PASS")
def test_pass():
    pass
"""


@pytest.mark.control(target="scaffold", expect="not-run")
def test_abort_replaces_previous_report(tmp_path):
    """Abbruch nach grünem Lauf: kein alter Bericht bleibt stehen"""
    files = {"catalog.toml": catalog("DEMO-PASS")}
    first = run_inner(
        tmp_path, {**files, "test_samples.py": GREEN}, "--spec"
    )
    assert first.code == pytest.ExitCode.OK, first.output
    broken = {**files, "test_samples.py": "def kaputt(:\n"}
    second = run_inner(tmp_path, broken, "--spec")
    assert second.code == pytest.ExitCode.INTERRUPTED
    assert second.report is None
    note = (tmp_path / "report" / "report.md").read_text()
    assert note.startswith("# Anforderungstests: abgebrochen")


@pytest.mark.control(target="scaffold", expect="passed")
def test_revision_distinguishes_worktrees(tmp_path):
    """Gleicher Commit, anderer Arbeitsstand: anderer Standnachweis"""
    git = local["git"]
    with local.env(GIT_AUTHOR_NAME="s", GIT_AUTHOR_EMAIL="s@x.invalid",
                   GIT_COMMITTER_NAME="s",
                   GIT_COMMITTER_EMAIL="s@x.invalid"):
        git("-C", tmp_path, "init", "-q")
        (tmp_path / "add.py").write_text("def add(a, b): a - b\n")
        git("-C", tmp_path, "add", "-A")
        git("-C", tmp_path, "commit", "-q", "-m", "start")
    clean = read_revision(tmp_path)
    (tmp_path / "add.py").write_text("def add(a, b): a + b\n")
    fixed = read_revision(tmp_path)
    (tmp_path / "notiz.txt").write_text("neu\n")
    untracked = read_revision(tmp_path)
    assert (clean["dirty"], clean["worktree"]) == (False, None)
    assert fixed["commit"] == clean["commit"]
    assert fixed["dirty"] and untracked["dirty"]
    assert len({fixed["worktree"], untracked["worktree"]}) == 2
    assert read_revision(tmp_path) == untracked
