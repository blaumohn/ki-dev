"""Übergaben im einen Ausführer (ki-dev-ablauf-ige.6.1, 6.2).

Derselbe Ablauf läuft mit Agenten (hier mock) ohne Halt bis zum Ende;
mit dem Boten hält er in ``awaiting_input`` und setzt mit der Antwort
fort, wie ``ki-dev step``.
"""

from __future__ import annotations

import copy
import json

import pytest

from ki_dev.adapter.contract import AnswerPending
from ki_dev.adapter.mock import MockAnswers
from ki_dev.flow.binding import OperationSpec
from ki_dev.flow.model import parse_flow, read_raw
from ki_dev.run_store import RunStore, RunStoreError
from ki_dev.runner.bound import BoundOperations
from ki_dev.runner.dispatch import Dispatch, role_of
from ki_dev.runner.package import PackageRunner
from ki_dev.runner.review_model import ReviewModel
from tests.executor_specs import LOCAL

STAND = {"tree": "a1b2c3d", "bead": "40"}


def _flow():
    """implement_review mit einem Vorlauf, dessen Ergebnis in die
    Laufdaten geht (Tatsachen, geprüfter Stand)."""
    raw = copy.deepcopy(read_raw("implement_review"))
    raw["op"]["checks"]["output"] = {
        "facts": ["facts"],
        "checked": ["checked"],
    }
    return parse_flow(raw)


FLOW = _flow()


def _catalog():
    def checks():
        return {
            "event": "checks_passed",
            "facts": ["full_checks"],
            "checked": STAND,
        }

    return {
        "checks.preflight": OperationSpec(
            checks, {"type": "array", "maxItems": 0}, {"type": "object"}
        )
    }


def _read(handoff, answer):
    """Antwort → Ereignis; der Stand der Antwort ist der geprüfte."""
    value = json.loads(answer)
    assert value["attempt"] == handoff.attempt
    return {"current": STAND}, value["event"]


def _runner(tmp_path, executors):
    turns = Dispatch(
        FLOW,
        executors,
        render=lambda h: f"Übergabe {h.state} {h.attempt}",
        read=_read,
        workdir=tmp_path,
    )
    return PackageRunner(
        FLOW,
        BoundOperations(FLOW.bindings, _catalog()),
        RunStore(tmp_path, "b"),
        model=ReviewModel,
        turns=turns,
    )


def _answer(event):
    return json.dumps({"attempt": "{attempt}", "event": event})


class Inbox:
    """Bote: gibt aus, antwortet erst, wenn eine Antwort vorliegt."""

    spec = LOCAL

    def __init__(self):
        self.answers = {}
        self.prompts = []

    def ask(self, request):
        if request.key in self.answers:
            return self.answers.pop(request.key)
        self.prompts.append(request.prompt)
        raise AnswerPending("Antwort fehlt")


def test_roles_come_from_the_flow():
    assert role_of(FLOW, "implement") == "worker"
    assert role_of(FLOW, "implement.review") == "review"
    assert role_of(FLOW, "implement.decision") is None


def test_agents_run_the_flow_to_the_end(tmp_path):
    worker = MockAnswers(LOCAL, [_answer("done"), _answer("done")])
    review = MockAnswers(LOCAL, [_answer("fix"), _answer("PASS")])
    run = _runner(tmp_path, {"worker": worker, "review": review})
    result = run.start({})
    assert result["status"] == result["state"] == "finished"
    assert [p.split()[1] for p in worker.prompts] == [
        "implement",
        "implement.correction",
    ]
    assert [p.split()[1] for p in review.prompts] == [
        "implement.review",
        "implement.review",
    ]
    attempts = [p.split()[2] for p in worker.prompts + review.prompts]
    assert attempts == ["b:1", "b:3", "b:2", "b:4"]


def test_messenger_halts_and_the_answer_resumes(tmp_path):
    inbox = Inbox()
    review = MockAnswers(LOCAL, [_answer("PASS")])
    run = _runner(tmp_path, {"worker": inbox, "review": review})
    halt = run.start({})
    assert (halt["status"], halt["state"]) == (
        "awaiting_input",
        "implement",
    )
    assert halt["attempt"] == "b:1"
    assert inbox.prompts == ["Übergabe implement b:1"]
    inbox.answers["b:1"] = _answer("done").replace("{attempt}", "b:1")
    done = run.resume()
    assert done["state"] == "finished"
    assert [(t.source, t.event) for t in done["path"]] == [
        ("implement", "done"),
        ("implement.preflight", "checks_passed"),
        ("implement.review", "PASS"),
    ]


def test_start_at_a_state(tmp_path):
    review = MockAnswers(LOCAL, [_answer("PASS")])
    run = _runner(tmp_path, {"worker": Inbox(), "review": review})
    result = run.start({}, "implement.preflight")
    assert result["state"] == "finished"
    assert result["path"][0].source == "implement.preflight"


def test_role_without_executor_is_a_visible_error(tmp_path):
    run = _runner(tmp_path, {"review": Inbox()})
    with pytest.raises(RunStoreError, match="kein Executor"):
        run.start({})
