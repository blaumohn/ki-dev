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
