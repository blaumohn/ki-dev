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
    MachineState,
    Phase,
    ProtocolError,
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


@pytest.mark.parametrize(
    "field_name",
    [
        "protocol_attempts",
        "worker_attempts",
        "changes_rounds",
        "process_retries",
    ],
)
def test_limits_need_one_attempt(field_name: str):
    with pytest.raises(ValueError, match="mindestens 1"):
        Limits(**{field_name: 0})


def test_state_rejects_untyped_phase():
    with pytest.raises(TypeError, match="Phase"):
        MachineState(phase="controller_step")


def test_state_rejects_untyped_review_flag():
    with pytest.raises(TypeError, match="echter bool"):
        MachineState(
            phase=Phase.CONTROLLER_STEP, checkpointed_result="ja"
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
