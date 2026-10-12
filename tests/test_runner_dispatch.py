"""Übergaben an Executoren je Rolle (ki-dev-ablauf-ige.6.1).

Derselbe Ablauf läuft mit Agenten (hier mock) ohne Halt bis zum Ende
und hält ohne Executor wie ``ki-dev step``: der Mensch ist Bote.
"""

from __future__ import annotations

import json
from dataclasses import replace

from ki_dev.adapter.contract import AnswerPending
from ki_dev.adapter.mock import MockAnswers
from ki_dev.flow.model import load_flow
from ki_dev.ops.checks import PREFLIGHT
from ki_dev.runner.dispatch import Dispatch, role_of
from ki_dev.runner.planning import TURN, planning_runtime, with_facts
from tests.executor_specs import LOCAL

FLOW = load_flow("implement_review")
STAND = {"tree": "a1b2c3d", "bead": "40"}


def _checks():
    def run(_state, context):
        facts = frozenset({"full_checks"})
        return "checks_passed", with_facts(
            context, facts, "checks_passed", STAND
        )

    return {PREFLIGHT: run}


def _read(halt, answer):
    """Antwort → Ereignis: Schreiben ist getan, das Review nennt sein
    Ereignis; der Stand der Antwort ist der geprüfte."""
    value = json.loads(answer)
    assert value["attempt"] == halt.attempt
    return value["event"], replace(halt.context, current=STAND)


def _dispatch(tmp_path, executors):
    return Dispatch(
        FLOW,
        executors,
        render=lambda halt: f"Übergabe {halt.state} {halt.attempt}",
        read=_read,
        workdir=tmp_path,
    )


def _answer(event):
    return json.dumps({"attempt": "{attempt}", "event": event})


def test_roles_come_from_the_flow():
    assert role_of(FLOW, "implement") == "worker"
    assert role_of(FLOW, "implement.review") == "review"
    assert role_of(FLOW, "implement.decision") is None


def test_agents_run_the_flow_to_the_end(tmp_path):
    worker = MockAnswers(LOCAL, [_answer("done"), _answer("done")])
    review = MockAnswers(LOCAL, [_answer("fix"), _answer("PASS")])
    turns = _dispatch(tmp_path, {"worker": worker, "review": review})
    with planning_runtime(
        FLOW, tmp_path / "lauf", "b", _checks(), turns
    ) as runtime:
        halt = runtime.start("implement", None)
    assert (halt.state, halt.operation) == ("finished", None)
    assert [p.split()[1] for p in worker.prompts] == [
        "implement",
        "implement.correction",
    ]
    assert [p.split()[1] for p in review.prompts] == [
        "implement.review",
        "implement.review",
    ]
    # Jede Antwort trägt die Kennung ihres Versuchs.
    attempts = [p.split()[2] for p in worker.prompts + review.prompts]
    assert len(set(attempts)) == 4


def test_without_executor_the_run_halts_like_step(tmp_path):
    turns = _dispatch(tmp_path, {})
    with planning_runtime(
        FLOW, tmp_path / "lauf", "b", _checks(), turns
    ) as runtime:
        halt = runtime.start("implement", None)
    assert (halt.state, halt.operation) == ("implement", TURN)


def test_missing_answer_halts_and_resumes_at_the_turn(tmp_path):
    class Pending:
        spec = LOCAL

        def ask(self, _request):
            raise AnswerPending("Antwort fehlt")

    worker = MockAnswers(LOCAL, [_answer("done")])
    turns = _dispatch(tmp_path, {"worker": worker, "review": Pending()})
    with planning_runtime(
        FLOW, tmp_path / "lauf", "b", _checks(), turns
    ) as runtime:
        halt = runtime.start("implement", None)
        assert halt.state == "implement.review"
        assert halt.operation == TURN
        assert runtime.waiting() == (
            "implement.review",
            frozenset({"full_checks"}),
        )
