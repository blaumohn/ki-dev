"""Gerüst ki_dev.fsm: die stillen Fallen der Bibliothek sind geschlossen
(Namen, strikte Ereignisse, raise ohne Empfänger, History im
Datensatz) und der Datensatz wird atomar ersetzt."""

from __future__ import annotations

import copy
import json
import os

import pytest

from ki_dev.fsm import (
    Durable,
    FsmError,
    RecordError,
    TransitionNotAllowed,
    bind,
    configuration_of,
)
from ki_dev.run_store import RunStore

DOC = {
    "name": "probe",
    "states": {
        "running": {
            "initial": True,
            "history": {"h": {"type": "shallow"}},
            "transitions": [
                {
                    "event": "stop",
                    "target": "awaiting_input",
                    "on": [{"raise": {"event": "escalation.guard"}}],
                }
            ],
            "states": {
                "review": {
                    "initial": True,
                    "transitions": [
                        {
                            "event": "fix",
                            "cond": "rounds_left",
                            "target": "worker",
                            "on": "count_round",
                        },
                        {"event": "fix", "target": "awaiting_input"},
                    ],
                },
                "worker": {
                    "transitions": [
                        {"event": "done", "target": "review"}
                    ]
                },
            },
        },
        "awaiting_input": {
            "transitions": [
                {"event": "escalation", "on": "escalate"},
                {"event": "resume", "target": "h"},
            ]
        },
    },
}


class Ops:
    def __init__(self, rounds: int = 0) -> None:
        self.rounds = rounds
        self.escalation: str | None = None

    def rounds_left(self, limit: int = 1) -> bool:
        return self.rounds < limit

    def count_round(self) -> None:
        self.rounds += 1

    def escalate(self, event: object) -> None:
        self.escalation = str(event).removeprefix("escalation.")


CHART = bind(DOC, Ops)


def test_typo_in_guard_fails_on_load_with_its_name():
    doc = copy.deepcopy(DOC)
    doc["states"]["running"]["states"]["review"]["transitions"][0][
        "cond"
    ] = "tippfehler_left"
    with pytest.raises(FsmError, match="fehlt: tippfehler_left"):
        bind(doc, Ops)


def test_unused_ops_callable_is_reported():
    class More(Ops):
        def zaubern(self) -> None: ...

    with pytest.raises(FsmError, match="ungenutzt: zaubern"):
        bind(DOC, More)


def test_expression_in_guard_is_rejected():
    doc = copy.deepcopy(DOC)
    doc["states"]["running"]["states"]["review"]["transitions"][0][
        "cond"
    ] = "round < 1"
    with pytest.raises(FsmError, match="keine Ausdrücke"):
        bind(doc, Ops)


def test_structured_action_other_than_raise_is_rejected():
    doc = copy.deepcopy(DOC)
    doc["states"]["running"]["transitions"][0]["on"] = [
        {"assign": {"location": "rounds", "expr": "0"}}
    ]
    with pytest.raises(FsmError, match="nur raise"):
        bind(doc, Ops)


def test_callback_named_like_an_event_is_rejected():
    """Die Bibliothek sendete sonst das Ereignis ``done``."""
    doc = copy.deepcopy(DOC)
    doc["states"]["running"]["states"]["review"]["transitions"][0][
        "on"
    ] = "done"

    class Clash(Ops):
        count_round = None

        def done(self) -> None: ...

    with pytest.raises(FsmError, match="wie ein Ereignis: done"):
        bind(doc, Clash)


def test_name_shadowing_the_library_is_rejected():
    """``prepare`` ist ein Attribut der Bibliothek; als Ereignis
    zerbräche es die Maschine beim Start."""
    doc = copy.deepcopy(DOC)
    doc["states"]["running"]["states"]["worker"]["transitions"][0][
        "event"
    ] = "prepare"
    with pytest.raises(FsmError, match="Bibliothek: prepare"):
        bind(doc, Ops)


def test_raise_without_receiver_is_rejected():
    doc = copy.deepcopy(DOC)
    doc["states"]["awaiting_input"]["transitions"].pop(0)

    class Fewer(Ops):
        escalate = None

    with pytest.raises(FsmError, match="raise escalation.guard"):
        bind(doc, Fewer)


def test_event_without_transition_is_not_allowed():
    machine = Durable(CHART, Ops())
    with pytest.raises(TransitionNotAllowed):
        machine.send("done")


def test_callback_error_propagates_instead_of_becoming_an_event():
    class Failing(Ops):
        def count_round(self) -> None:
            raise RuntimeError("kaputt")

    machine = Durable(bind(DOC, Failing), Failing())
    with pytest.raises(RuntimeError, match="kaputt"):
        machine.send("fix")


def test_history_survives_a_new_instance():
    """Spike t6: speichern im Halt, neue Instanz, resume."""
    first = Ops()
    machine = Durable(CHART, first)
    machine.send("fix")
    machine.send("stop")
    assert machine.configuration == ["awaiting_input"]
    assert first.escalation == "guard"
    record = json.loads(json.dumps(machine.record))

    resumed = Durable(CHART, Ops(first.rounds), record)
    taken = resumed.send("resume")

    assert resumed.configuration == ["running", "worker"]
    assert (taken.owner, taken.index) == ("awaiting_input", 1)


@pytest.mark.parametrize(
    "state", [["awaiting_input"], ["running", "worker"]]
)
def test_record_round_trips_through_json(state: list[str]):
    record = {"state": state, "history": {"h": ["review"]}}
    machine = Durable(CHART, Ops(), json.loads(json.dumps(record)))
    assert machine.record == record


def test_restoring_does_not_repeat_entry_actions():
    machine = Durable(
        CHART, Ops(), {"state": ["running", "worker"], "history": {}}
    )
    taken = machine.send("done")
    assert machine.configuration == ["running", "review"]
    assert (taken.owner, taken.index) == ("worker", 0)


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({"state": []}, "history: required"),
        ({"state": ["nirgends"], "history": {}}, "unbekannte"),
        (
            {"state": ["awaiting_input"], "history": {"x": ["review"]}},
            "kein History",
        ),
    ],
)
def test_invalid_record_is_rejected(record: dict, message: str):
    with pytest.raises(RecordError, match=message):
        Durable(CHART, Ops(), record)


def test_model_must_be_the_bound_ops():
    with pytest.raises(TypeError, match="Ops"):
        Durable(CHART, object())


def test_configuration_of_names_ancestors_first():
    assert configuration_of(CHART, "worker") == ["running", "worker"]


def test_record_keeps_old_content_when_replace_is_interrupted(
    tmp_path, monkeypatch
):
    store = RunStore(tmp_path, "run-x")
    store.save_record({"state": ["running"], "history": {}})

    def interrupted(*_: object) -> None:
        raise SystemExit("Abbruch vor dem Ersetzen")

    monkeypatch.setattr(os, "replace", interrupted)
    with pytest.raises(SystemExit):
        store.save_record({"state": ["awaiting_input"], "history": {}})

    assert store.load_record() == {"state": ["running"], "history": {}}
    assert [p.name for p in store.run_dir.iterdir()] == ["record.json"]
