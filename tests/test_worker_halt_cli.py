"""Worker-Halt über die CLI, ohne Agenten und ohne Folgeoperationen."""

import json
from pathlib import Path

import pytest

from tests.test_review_gate_cli import _implement


@pytest.mark.parametrize(
    ("outcome", "status"),
    [
        ("needs_decision", "waiting_decision"),
        ("escalate", "paused_interactive"),
    ],
)
def test_worker_halt_persists_reason_without_followup(
    sandbox, outcome, status
):
    reason = "Vorgaben widersprechen sich; Entscheidung erforderlich."
    run = _implement(
        sandbox,
        "+",
        worker_answer=json.dumps(
            {"outcome": outcome, "summary": reason}
        ),
        worker_changes=False,
    )
    assert run["result"]["status"] == status
    assert reason in run["result"]["detail"]
    assert run["before"] == run["after"]
    assert run["checks"] == []
    assert not run["test_marker"].exists()
    events = {event["event"] for event in run["events"]}
    assert f"worker_{outcome}" in events
    assert not events.intersection({"worker_completed", "PASS"})
    assert len(list((run["run"] / "inbox").glob("*.input.md"))) == 1
    record = json.loads((run["run"] / "record.json").read_text())
    assert record["data"]["work_report"] == reason
    assert record["data"]["review_sequence"] == 0
    handoffs = list((run["run"] / "handoff").glob("*.json"))
    assert any(
        json.loads(p.read_text())["needed_decision"] == reason
        for p in handoffs
    )

    status_result = sandbox.run(
        [
            "ki-dev",
            "-f",
            "implement",
            "status",
            "r",
            "--runs-dir",
            run["run"].parent,
        ],
        cwd=run["work"],
    )
    assert status_result.code == 0, status_result.stderr
    persisted = json.loads(status_result.stdout)
    assert persisted["status"] == status
    assert reason in persisted["detail"]


def test_history_names_worker_question_in_full_before_halt(sandbox):
    """Die Frage des Umsetzers steht als eigene Zeile, umbrochen statt
    gekürzt; der Halt verweist nur noch auf die Entscheidung."""
    reason = "Vorgaben widersprechen sich; Entscheidung erforderlich."
    run = _implement(
        sandbox,
        "+",
        worker_answer=json.dumps(
            {"outcome": "needs_decision", "summary": reason}
        ),
        worker_changes=False,
    )
    history = sandbox.run(
        ["ki-dev", "-f", "implement", "history", "r",
         "--runs-dir", run["run"].parent],
        cwd=run["work"],
    )
    assert history.code == 0, history.stderr
    lines = history.stdout.splitlines()
    assert lines[1].split()[:4] == ["Runde", "1", "Umsetzer", "Frage:"]
    question = " ".join(" ".join(lines[1:-1]).split()[3:])
    assert question == f"Frage: {reason}"
    assert lines[-1].split() == [
        "Halt", "wartet", "auf", "Entscheidung", "(Bead", "ändern,",
        "resume)",
    ]
    assert all(len(line) <= 78 for line in lines)

    def ki_dev(*args):
        outcome = sandbox.run(
            ["ki-dev", "-f", "implement", *args, "--runs-dir",
             run["run"].parent],
            cwd=run["work"],
        )
        assert outcome.code == 0, outcome.stderr
        return outcome.stdout

    ki_dev("resume", "r", "--answer", "Test anpassen")
    (ask,) = [
        path for path in (run["run"] / "inbox").glob("*.input.md")
        if not path.with_name(
            path.name.replace(".input.", ".answer.")
        ).exists()
    ]
    ask.with_name(ask.name.replace(".input.", ".answer.")).write_text(
        json.dumps({"outcome": "completed", "summary": "Fertig"})
    )
    (run["work"] / "MOCK.md").write_text("Änderung nach der Antwort\n")
    assert json.loads(ki_dev("resume", "r"))["status"] == "passed"

    actors = [
        line.split()[2] for line in ki_dev("history", "r").splitlines()
        if line.startswith("  Runde ")
    ]
    assert actors == [
        "Umsetzer", "Mensch", "Umsetzer", "Tests", "Review",
    ]


def test_completed_worker_still_runs_checks_review_and_integration(
    sandbox,
):
    run = _implement(
        sandbox,
        "+",
        worker_answer=json.dumps(
            {"outcome": "completed", "summary": "Fertig"}
        ),
    )
    assert run["result"]["status"] == "passed"
    assert run["before"] != run["after"]
    assert [check["passed"] for check in run["checks"]] == [True]
    assert any(event["event"] == "PASS" for event in run["events"])


def test_invalid_worker_protocol_does_not_become_decision_or_success(
    sandbox,
):
    run = _implement(
        sandbox, "+", worker_answer='{"outcome":"unknown"}'
    )
    assert run["result"]["status"] == "awaiting_input"
    inputs = sorted((run["run"] / "inbox").glob("*.input.md"))
    assert len(inputs) == 2
    assert "Worker-JSON verlangt" in inputs[1].read_text()
    assert run["before"] == run["after"]
    assert run["checks"] == []
    assert not run["test_marker"].exists()
    assert any(
        event["event"] == "protocol_error" for event in run["events"]
    )


def test_worker_escalation_resumes_at_worker_not_reviewer(sandbox):
    run = _implement(
        sandbox,
        "+",
        worker_answer=json.dumps(
            {"outcome": "escalate", "summary": "Zugriff fehlt"}
        ),
        worker_changes=False,
    )
    assert run["result"]["status"] == "paused_interactive"
    assert run["result"]["detail"] == "Zugriff fehlt"

    resumed = _resume(sandbox, run, decision="Zugriff ist eingerichtet")
    assert resumed["status"] == "awaiting_input"
    events = _events(run["run"])
    assert not any(event["event"] == "PASS" for event in events)
    inputs = sorted((run["run"] / "inbox").glob("*.input.md"))
    assert len(inputs) == 2
    assert "Zugriff ist eingerichtet" in inputs[1].read_text()

    (run["work"] / "MOCK.md").write_text("Änderung des Workers\n")
    finished = _resume(
        sandbox,
        run,
        answer=json.dumps(
            {"outcome": "completed", "summary": "Zugriff geklärt"}
        ),
    )
    assert finished["status"] == "passed"
    names = [event["event"] for event in _events(run["run"])]
    assert names.index("worker_escalate") < names.index(
        "worker_completed"
    ) < names.index("PASS")


@pytest.mark.parametrize("outcome", ["needs_decision", "escalate"])
def test_worker_halt_after_change_goes_through_review(sandbox, outcome):
    """Hält der Worker nach eigener Änderung an (behaupteter
    Widerspruch, Aufgeben bei rotem Test), hält der Lauf nicht allein
    deshalb: Nachweis, Test-Tor und Review beurteilen die Runde; hier
    sind die Tests grün und das Review sagt PASS."""
    reason = "Test bleibt rot, ich komme nicht weiter."
    run = _implement(
        sandbox,
        "+",
        worker_answer=json.dumps(
            {"outcome": outcome, "summary": reason}
        ),
    )
    assert run["result"]["status"] == "passed"
    names = [event["event"] for event in run["events"]]
    assert names.index(f"worker_{outcome}") < names.index(
        "step_result_captured"
    ) < names.index("PASS")
    assert run["checks"], "Test-Tor lief nicht"
    record = json.loads((run["run"] / "record.json").read_text())
    assert record["data"]["work_report"] == reason


def _resume(
    sandbox,
    run,
    *,
    decision: str | None = None,
    answer: str | None = None,
) -> dict:
    """Fortsetzen über die CLI; ``decision`` ist die Antwort des
    Menschen auf den Halt, ``answer`` beantwortet vorher die offene
    Boten-Eingabe des Workers."""
    if answer is not None:
        ask = sorted((run["run"] / "inbox").glob("*.input.md"))[-1]
        reply = ask.name.replace(".input.", ".answer.")
        ask.with_name(reply).write_text(answer)
    command = ["ki-dev", "-f", "implement", "resume", "r",
               "--runs-dir", run["run"].parent]
    if decision is not None:
        command += ["--answer", decision]
    outcome = sandbox.run(command, cwd=run["work"])
    assert outcome.code == 0, outcome.stderr
    return json.loads(outcome.stdout)


def _events(run: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in (run / "events.jsonl").read_text().splitlines()
    ]
