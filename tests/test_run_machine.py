"""Lauf-Maschine (runner/run.toml): je Kante ein Test, dazu die
Abweisung unpassender Fortsetzungen. Halte, die der Ablauf auslöst
(Eskalation, Warten, Ende), kommen über die Region ``ablauf`` derselben
Maschine, nicht als Ereignis des Ausführers."""

from __future__ import annotations

import json

import pytest

from ki_dev.flow_ops.implement.machine import (
    ControllerEscalate,
    ControllerNeedsDecision,
    FinalizationError,
    IntegrationCompleted,
    MachineState,
    Phase,
    RunState,
)
from ki_dev.flow_ops.implement.run_machine import RunMachine
from ki_dev.fsm import TransitionNotAllowed

_WORK = {"id": "r0001-work", "kind": "work", "repeatable": False}
_FINAL = {
    "id": "final-integrate",
    "kind": "integrate",
    "repeatable": True,
}


def _at(*events: str, operation: dict = _WORK) -> RunMachine:
    machine = RunMachine()
    for event in events:
        if event == "hold":
            machine.send(event, operation=operation)
        else:
            machine.send(event)
    return machine


def _reloaded(machine: RunMachine) -> RunMachine:
    """Über die Prozessgrenze: Datensatz als JSON, neue Instanz; den
    Ablaufzustand liefern die Laufdaten."""
    record = json.loads(json.dumps(machine.record))
    return RunMachine(
        record,
        json.loads(json.dumps(machine.pending)),
        MachineState(phase=machine.phase),
    )


def _flow_at(phase: Phase) -> RunMachine:
    return RunMachine(
        {"state": ["lauf", "operation", "idle", "halt", "running"],
         "history": {}},
        None,
        MachineState(phase=phase),
    )


_FLOW_HALTS = {
    "paused_interactive": (
        Phase.CONTROLLER_STEP, ControllerEscalate("unklar")
    ),
    "waiting_decision": (
        Phase.CONTROLLER_STEP, ControllerNeedsDecision("welche?")
    ),
    "passed": (
        Phase.FAST_FORWARD_INTEGRATE, IntegrationCompleted(ok=True)
    ),
    "error": (Phase.FAST_FORWARD_INTEGRATE, FinalizationError("weg")),
}


def _halted_by_flow(halt: str) -> RunMachine:
    phase, event = _FLOW_HALTS[halt]
    machine = _flow_at(phase)
    machine.advance(
        RunState("r-1", 0, MachineState(phase=phase)), event
    )
    return machine


def test_new_run_is_running_without_operation():
    machine = RunMachine()
    assert (machine.status, machine.halted, machine.pending) == (
        "running",
        False,
        None,
    )


def test_hold_keeps_the_operation_without_call():
    machine = _at("hold")
    assert machine.pending == {**_WORK, "call_id": None}
    assert not machine.started


def test_start_records_the_intention():
    machine = _at("hold")
    machine.send("start", call_id="c-1")
    assert machine.started
    assert machine.pending["call_id"] == "c-1"


@pytest.mark.parametrize("before", [("hold",), ("hold", "start")])
def test_saved_artifact_ends_the_operation(before: tuple[str, ...]):
    machine = _at(*before)
    machine.send("artifact_saved")
    assert machine.pending is None
    assert machine.status == "running"


@pytest.mark.parametrize(
    "before", [(), ("hold",), ("hold", "start")]
)
def test_failure_ends_any_operation(before: tuple[str, ...]):
    machine = _at(*before)
    machine.send("failed")
    assert machine.pending is None
    assert not machine.halted


def test_answer_pending_halts_the_executor_and_keeps_the_operation():
    machine = _reloaded(_at("hold", "start"))
    machine.send("answer_pending")
    assert machine.status == "awaiting_input"
    assert machine.pending["id"] == _WORK["id"]


def test_resume_after_relay_prepares_the_same_operation_again():
    machine = _reloaded(_at("hold", "start", "answer_pending"))
    machine.send("resume")
    assert machine.status == "running"
    assert not machine.started
    assert machine.pending["id"] == _WORK["id"]


def test_answer_text_does_not_fit_a_relay():
    machine = _at("hold", "start", "answer_pending")
    with pytest.raises(TransitionNotAllowed):
        machine.send("answer")


def test_interrupted_effect_is_uncertain():
    machine = _reloaded(_at("hold", "start"))
    machine.send("resume")
    machine.send("interrupted")
    assert machine.status == "uncertain"
    assert machine.halted
    assert machine.pending["id"] == _WORK["id"]


def test_interrupted_repeatable_effect_runs_again():
    machine = _reloaded(_at("hold", "start", operation=_FINAL))
    machine.send("interrupted")
    assert machine.status == "running"
    assert machine.started


def test_reconcile_returns_to_the_started_operation():
    machine = _at("hold", "start", "interrupted")
    machine.send("reconcile")
    assert machine.started
    assert machine.status == "running"


@pytest.mark.parametrize(
    "halt", ["paused_interactive", "waiting_decision"]
)
def test_waiting_halts_need_an_answer(halt: str):
    machine = _reloaded(_halted_by_flow(halt))
    assert machine.status == halt
    assert machine.halted
    with pytest.raises(TransitionNotAllowed):
        machine.send("resume")
    machine.send("answer")
    assert machine.status == "running"
    assert machine.pending is None


@pytest.mark.parametrize("final", ["passed", "error"])
def test_final_halts_take_nothing(final: str):
    machine = _reloaded(_halted_by_flow(final))
    assert machine.status == final
    assert machine.halted
    for event in ("resume", "answer", "reconcile"):
        with pytest.raises(TransitionNotAllowed):
            machine.send(event)


def test_resume_while_running_continues_where_the_record_stands():
    machine = _reloaded(_at("hold", "start"))
    machine.send("resume")
    assert machine.started


def test_answer_while_running_is_not_allowed():
    with pytest.raises(TransitionNotAllowed):
        RunMachine().send("answer")


def test_allowed_events_name_the_possible_continuation():
    assert _halted_by_flow("waiting_decision").allowed == ["answer"]


def test_escalation_halts_the_run_and_keeps_the_flow():
    """Eine Eskalation hält in halt an; der Ablauf bleibt, wo er war,
    und nach der Antwort fährt der Lauf dort weiter."""
    machine = _halted_by_flow("paused_interactive")
    assert machine.phase is Phase.CONTROLLER_STEP
    machine.send("answer")
    assert (machine.status, machine.phase) == (
        "running",
        Phase.CONTROLLER_STEP,
    )


def test_operation_waits_while_the_run_is_halted():
    machine = _halted_by_flow("paused_interactive")
    with pytest.raises(TransitionNotAllowed):
        machine.send("hold", operation=_WORK)


def test_flow_state_and_run_data_must_agree():
    with pytest.raises(RuntimeError, match="Ablauf steht in start"):
        RunMachine().advance(
            RunState(
                "r-1", 0, MachineState(phase=Phase.CONTROLLER_STEP)
            ),
            ControllerEscalate("unklar"),
        )
