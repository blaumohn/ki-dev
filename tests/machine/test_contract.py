from __future__ import annotations

import pytest

from ki_dev.deltas import StepDeltaAssessment
from ki_dev.machine import (
    AgentEscalation,
    ControllerChanges,
    ControllerEscalate,
    ControllerNeedsDecision,
    ControllerTask,
    Counters,
    FinalizationError,
    FinalResultVerified,
    IntegrationCompleted,
    Limits,
    MachineEscalation,
    MachineEscalationCause,
    MachineState,
    Phase,
    ProtocolError,
    RunState,
    StepResultCaptured,
    WorkerEscalate,
    WorkerNeedsDecision,
    WorkerProcessError,
)


@pytest.mark.parametrize(
    "build",
    [
        lambda: ControllerTask("  "),
        lambda: ControllerChanges(""),
        lambda: ControllerNeedsDecision("\t"),
        lambda: ControllerEscalate(" "),
        lambda: WorkerNeedsDecision(""),
        lambda: WorkerEscalate("   "),
        lambda: WorkerProcessError(""),
        lambda: ProtocolError("  "),
        lambda: FinalizationError(""),
        lambda: AgentEscalation("", Phase.WORKER_STEP),
    ],
)
def test_empty_mandatory_text_is_rejected(build):
    with pytest.raises(ValueError, match="darf nicht leer sein"):
        build()


@pytest.mark.parametrize(
    "value",
    ["false", "", 1, 0, None, [], object()],
)
def test_verification_needs_real_bool(value):
    with pytest.raises(TypeError, match="echter bool"):
        FinalResultVerified(ok=value)


@pytest.mark.parametrize(
    "value",
    ["false", "", 1, 0, None, [], object()],
)
def test_integration_needs_real_bool(value):
    with pytest.raises(TypeError, match="echter bool"):
        IntegrationCompleted(ok=value)


@pytest.mark.parametrize("value", [True, False])
def test_real_bools_are_accepted(value: bool):
    assert FinalResultVerified(ok=value).ok is value
    assert IntegrationCompleted(ok=value).ok is value


@pytest.mark.parametrize(
    "value",
    ["effective", "empty_unexplained", None, 0],
)
def test_assessment_must_be_typed(value):
    with pytest.raises(TypeError, match="StepDeltaAssessment"):
        StepResultCaptured(assessment=value)


def test_worker_signal_is_not_a_capture():
    with pytest.raises(ValueError, match="eigenes Ereignis"):
        StepResultCaptured(
            assessment=StepDeltaAssessment.EMPTY_WITH_SIGNAL
        )


@pytest.mark.parametrize(
    "assessment",
    [
        StepDeltaAssessment.EFFECTIVE,
        StepDeltaAssessment.EMPTY_UNEXPLAINED,
    ],
)
def test_capture_accepts_both_assessments(assessment):
    assert StepResultCaptured(assessment).assessment is assessment


def test_counters_reject_negative_values():
    with pytest.raises(ValueError, match="nicht negativ"):
        Counters(worker_attempt=-1)


_COUNTER_FIELDS = (
    "protocol_attempt",
    "worker_attempt",
    "process_retry",
    "changes_round",
)


@pytest.mark.parametrize("field_name", _COUNTER_FIELDS)
@pytest.mark.parametrize("value", [True, False, 1.0, "1"])
def test_counters_reject_untyped_values(field_name: str, value: object):
    with pytest.raises(TypeError, match="echter int"):
        Counters(**{field_name: value})


@pytest.mark.parametrize("field_name", _COUNTER_FIELDS)
def test_counters_reject_each_negative_field(field_name: str):
    with pytest.raises(ValueError, match="nicht negativ"):
        Counters(**{field_name: -1})


def test_run_total_ignores_task_rounds():
    counters = Counters(
        protocol_attempt=1,
        worker_attempt=2,
        process_retry=3,
        changes_round=4,
    )
    assert counters.run_total == 6


def test_a_new_task_resets_the_round_budget():
    before = Counters(worker_attempt=2, changes_round=2)
    after = before.started_task()
    assert after.changes_round == 0
    assert after.worker_attempt == 3
    assert after.run_total > before.run_total


def test_a_correction_spends_the_round_budget():
    before = Counters(worker_attempt=2, changes_round=1)
    after = before.started_correction()
    assert after.changes_round == 2
    assert after.worker_attempt == 3
    assert after.run_total > before.run_total


@pytest.mark.parametrize(
    ("step", "field_name"),
    [
        (Counters.retried_process, "process_retry"),
        (Counters.retried_protocol, "protocol_attempt"),
    ],
)
def test_retries_keep_the_round_budget(step, field_name: str):
    before = Counters(worker_attempt=1, changes_round=1)
    after = step(before)
    assert getattr(after, field_name) == 1
    assert after.changes_round == 1
    assert after.worker_attempt == 1
    assert after.run_total > before.run_total


_LIMIT_FIELDS = (
    "protocol_attempts",
    "worker_attempts",
    "changes_rounds",
    "process_retries",
)


@pytest.mark.parametrize("field_name", _LIMIT_FIELDS)
def test_limits_need_one_attempt(field_name: str):
    with pytest.raises(ValueError, match="mindestens 1"):
        Limits(**{field_name: 0})


@pytest.mark.parametrize("field_name", _LIMIT_FIELDS)
@pytest.mark.parametrize("value", [True, False, 3.0, "3"])
def test_limits_reject_untyped_values(field_name: str, value: object):
    with pytest.raises(TypeError, match="echter int"):
        Limits(**{field_name: value})


def test_state_rejects_untyped_phase():
    with pytest.raises(TypeError, match="Phase"):
        MachineState(phase="controller_step")


def test_state_rejects_untyped_review_flag():
    with pytest.raises(TypeError, match="echter bool"):
        MachineState(
            phase=Phase.CONTROLLER_STEP, checkpointed_result="ja"
        )


@pytest.mark.parametrize(
    "counters",
    [None, Counters, {"worker_attempt": 1}, (0, 0, 0, 0)],
)
def test_state_rejects_untyped_counters(counters: object):
    with pytest.raises(TypeError, match="muessen Counters sein"):
        MachineState(phase=Phase.START, counters=counters)


@pytest.mark.parametrize(
    "resume_point",
    [None, "worker_step", Phase.WORKER_STEP.value, 3],
)
def test_agent_escalation_typed_resume(resume_point: object):
    with pytest.raises(TypeError, match="muss eine Phase sein"):
        AgentEscalation("unklar", resume_point)


@pytest.mark.parametrize(
    "cause",
    [
        "worker_attempts_exhausted",
        None,
        MachineEscalationCause.INTEGRATION_FAILED.value,
    ],
)
def test_machine_escalation_typed_cause(cause: object):
    with pytest.raises(TypeError, match="MachineEscalationCause"):
        MachineEscalation(cause=cause, resume_point=Phase.WORKER_STEP)


@pytest.mark.parametrize(
    "resume_point",
    [None, "worker_step", Phase.WORKER_STEP.value],
)
def test_machine_escalation_typed_resume(resume_point: object):
    with pytest.raises(TypeError, match="muss eine Phase sein"):
        MachineEscalation(
            cause=MachineEscalationCause.INTEGRATION_FAILED,
            resume_point=resume_point,
        )


def test_state_defaults_to_no_result():
    state = MachineState(phase=Phase.START)
    assert state.checkpointed_result is False
    assert state.counters == Counters()
    assert state.is_stopped is False


@pytest.mark.parametrize(
    "phase",
    [
        Phase.PASSED,
        Phase.ERROR,
        Phase.WAITING_DECISION,
        Phase.PAUSED_INTERACTIVE,
    ],
)
def test_stopped_phases_are_recognised(phase: Phase):
    assert MachineState(phase=phase).is_stopped is True


def _run_state(**overrides: object) -> RunState:
    """Gueltiger Laufzustand, einzelne Felder gezielt ersetzt."""
    fields: dict[str, object] = {
        "run_id": "run-1",
        "revision": 0,
        "state": MachineState(phase=Phase.START),
    }
    fields.update(overrides)
    return RunState(**fields)  # type: ignore[arg-type]


def test_run_state_keeps_valid_values():
    state = MachineState(
        phase=Phase.CHECKPOINT,
        counters=Counters(worker_attempt=2),
        checkpointed_result=True,
    )
    limits = Limits(worker_attempts=7)
    escalation = AgentEscalation("unklar", Phase.WORKER_STEP)
    run = RunState(
        run_id="run-7",
        revision=3,
        state=state,
        limits=limits,
        escalation=escalation,
    )
    assert run.run_id == "run-7"
    assert run.revision == 3
    assert run.state is state
    assert run.limits is limits
    assert run.escalation is escalation


def test_run_state_defaults_are_open():
    run = _run_state()
    assert run.limits == Limits()
    assert run.escalation is None


@pytest.mark.parametrize("run_id", ["", "   ", "\t"])
def test_run_state_rejects_empty_run_id(run_id: str):
    with pytest.raises(ValueError, match="darf nicht leer sein"):
        _run_state(run_id=run_id)


@pytest.mark.parametrize("run_id", [None, 7, b"run"])
def test_run_state_rejects_untyped_run_id(run_id: object):
    with pytest.raises(TypeError, match="muss ein str sein"):
        _run_state(run_id=run_id)


def test_run_state_rejects_negative_revision():
    with pytest.raises(ValueError, match="darf nicht negativ sein"):
        _run_state(revision=-1)


@pytest.mark.parametrize("revision", [True, "0", 1.0, None])
def test_run_state_rejects_untyped_revision(revision: object):
    with pytest.raises(TypeError, match="echter int"):
        _run_state(revision=revision)


@pytest.mark.parametrize(
    "state",
    [None, Phase.START, "start", MachineState],
)
def test_run_state_rejects_untyped_state(state: object):
    with pytest.raises(TypeError, match="MachineState"):
        _run_state(state=state)


@pytest.mark.parametrize(
    "limits",
    [None, Limits, {"worker_attempts": 3}, (3, 3, 3, 3)],
)
def test_run_state_rejects_untyped_limits(limits: object):
    with pytest.raises(TypeError, match="muessen Limits sein"):
        _run_state(limits=limits)


@pytest.mark.parametrize(
    "escalation",
    [
        "unklar",
        Phase.WORKER_STEP,
        MachineEscalationCause.INTEGRATION_FAILED,
    ],
)
def test_run_state_rejects_untyped_escalation(escalation: object):
    with pytest.raises(TypeError, match="AgentEscalation oder"):
        _run_state(escalation=escalation)


def test_run_state_accepts_machine_escalation():
    escalation = MachineEscalation(
        cause=MachineEscalationCause.WORKER_ATTEMPTS_EXHAUSTED,
        resume_point=Phase.CONTROLLER_STEP,
    )
    assert _run_state(escalation=escalation).escalation is escalation
