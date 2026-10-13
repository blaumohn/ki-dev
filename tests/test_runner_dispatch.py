"""Übergaben im einen Ausführer (ki-dev-ablauf-ige.6.1–6.3).

Derselbe Ablauf läuft mit Agenten (hier mock) ohne Halt bis zum Ende;
mit dem Boten hält er in ``awaiting_input`` und setzt mit der Antwort
fort. Ein neuer Lauf im selben Protokoll beginnt
mit ``lauf --@start--> lauf``.
"""

from __future__ import annotations

import copy
import json

import pytest

from ki_dev.adapter.contract import AnswerPending
from ki_dev.adapter.mock import MockAnswers
from ki_dev.flow.binding import OperationSpec
from ki_dev.flow.model import parse_flow, read_raw
from ki_dev.flow_ops.review.model import ReviewModel
from ki_dev.run_store import RunStore, RunStoreError
from ki_dev.runner.bound import BoundOperations
from ki_dev.runner.dispatch import Dispatch, role_of
from ki_dev.runner.events import check_conformance
from ki_dev.runner.package import PackageRunner
from ki_dev.runner.protocol import RUN_DOC
from tests.executor_specs import LOCAL


def _flow():
    """implement_review mit einem Vorlauf, dessen Tatsachen in die
    Laufdaten gehen."""
    raw = copy.deepcopy(read_raw("implement_review"))
    raw["op"]["checks"]["output"] = {"facts": ["facts"]}
    return parse_flow(raw)


FLOW = _flow()


def _catalog(facts=("full_checks",)):
    def checks():
        return {"event": "checks_passed", "facts": list(facts)}

    return {
        "checks.preflight": OperationSpec(
            checks, {"type": "array", "maxItems": 0}, {"type": "object"}
        )
    }


def _read(handoff, answer):
    """Antwort → Ereignis."""
    value = json.loads(answer)
    assert value["attempt"] == handoff.attempt
    return {}, value["event"]


def _runner(tmp_path, executors, catalog=None):
    turns = Dispatch(
        FLOW,
        executors,
        render=lambda h: f"Übergabe {h.state} {h.attempt}",
        read=_read,
        workdir=tmp_path,
    )
    return PackageRunner(
        FLOW,
        BoundOperations(FLOW.bindings, catalog or _catalog()),
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


def _review_waits(tmp_path, catalog=None):
    """Lauf ab dem Vorlauf, der Bote hält im Review."""
    run = _runner(
        tmp_path, {"worker": Inbox(), "review": Inbox()}, catalog
    )
    halt = run.start({}, "implement.preflight")
    assert (halt["status"], halt["state"]) == (
        "awaiting_input",
        "implement.review",
    )
    return run


def test_answer_names_the_executor_in_the_log(tmp_path):
    review = MockAnswers(LOCAL, [_answer("PASS")])
    run = _runner(tmp_path, {"worker": Inbox(), "review": review})
    run.start({}, "implement.preflight")
    rows = [
        (e["state"], e["adapter"])
        for e in run.store.load_events()
        if e["region"] == "ablauf"
    ]
    assert rows == [
        ("implement.preflight", "ki-dev"),
        ("implement.review", LOCAL.name),
    ]


def test_new_run_starts_again_with_fresh_operations(tmp_path):
    """again: Neubeginn im selben Protokoll; der Vorlauf läuft erneut,
    statt das Ergebnis des alten Laufs wiederzuverwenden."""
    _review_waits(tmp_path)
    artifacts = tmp_path / "b" / "artifacts"
    assert len(list(artifacts.iterdir())) == 1
    run = _review_waits_again(tmp_path)
    assert len(list(artifacts.iterdir())) == 2
    events = run.store.load_events()
    assert [e["event"] for e in events if e["region"] == "lauf"] == [
        "@start"
    ]
    # Die Regionen des Laufs beginnen neu (konform); nur der Ablauf
    # springt vom Review zurück in den Vorlauf.
    problems = check_conformance(FLOW, events, RUN_DOC)
    assert [p.split(": ")[1] for p in problems] == [
        "keine Kante implement.review --@jump--> implement.preflight"
    ]


def _review_waits_again(tmp_path):
    run = _runner(tmp_path, {"worker": Inbox(), "review": Inbox()})
    halt = run.start({}, "implement.preflight", again=True)
    assert halt["state"] == "implement.review"
    return run


def test_new_run_elsewhere_is_a_jump(tmp_path):
    _review_waits(tmp_path)
    run = _runner(tmp_path, {"worker": Inbox(), "review": Inbox()})
    run.start({}, "implement", again=True)
    events = run.store.load_events()
    jump = [i for i, e in enumerate(events) if e["event"] == "@jump"]
    assert check_conformance(FLOW, events, RUN_DOC) == [
        f"{jump[0]}: keine Kante implement.review --@jump--> implement"
    ]


