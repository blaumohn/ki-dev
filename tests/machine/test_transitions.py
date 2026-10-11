from __future__ import annotations

import json

import pytest

from ki_dev.deltas import StepDeltaAssessment
from ki_dev.runner.machine import (
    STOPPED_PHASES,
    AgentEscalation,
    CheckpointRecorded,
    ControllerChanges,
    ControllerEscalate,
    ControllerNeedsDecision,
    ControllerPass,
    ControllerTask,
    Counters,
    Event,
    ExecutionStopped,
    FinalizationError,
    FinalResultVerified,
    HistoryFinalized,
    IntegrationCompleted,
    InvalidTransition,
    Limits,
    MachineEscalation,
    MachineEscalationCause,
    MachineState,
    Phase,
    ProcessError,
    ProtocolError,
    ResumeRequested,
    ReviewedResultFrozen,
    RunStarted,
    RunState,
    StepResultCaptured,
    WorkerCompleted,
    WorkerEscalate,
    WorkerInputsPrepared,
    WorkerNeedsDecision,
    WorkerProcessError,
    advance,
    decode_run_state,
    encode_run_state,
)

from .conftest import TRANSITIONS

_EFFECTIVE = StepResultCaptured(StepDeltaAssessment.EFFECTIVE)
_EMPTY = StepResultCaptured(StepDeltaAssessment.EMPTY_UNEXPLAINED)

_TIGHT = Limits(
    protocol_attempts=1,
    worker_attempts=2,
    changes_rounds=1,
    process_retries=1,
)


def _at(phase: Phase, **counters: int) -> MachineState:
    """Zustand ohne vorliegendes Worker-Ergebnis."""
    return MachineState(phase=phase, counters=Counters(**counters))


def _reviewed(**counters: int) -> MachineState:
    """Controller-Schritt mit gecheckpointetem Worker-Ergebnis."""
    return MachineState(
        phase=Phase.CONTROLLER_STEP,
        counters=Counters(**counters),
        checkpointed_result=True,
    )


# (Ausgangszustand, Ereignis, Zielphase, erwartete Eskalationsart)
_ALLOWED: list[tuple[MachineState, Event, Phase, type | None]] = [
    (_at(Phase.START), RunStarted(), Phase.CONTROLLER_STEP, None),
    # Erstmaliger Controller-Aufruf: beauftragen, fragen, eskalieren.
    (
        _at(Phase.CONTROLLER_STEP),
        ControllerTask("Implementiere X"),
        Phase.WORKER_STEP_PREPARE,
        None,
    ),
    (
        _at(Phase.CONTROLLER_STEP),
        ControllerNeedsDecision("Welche Ablage?"),
        Phase.WAITING_DECISION,
        None,
    ),
    (
        _at(Phase.CONTROLLER_STEP),
        ControllerEscalate("Sitzung unklar"),
        Phase.PAUSED_INTERACTIVE,
        AgentEscalation,
    ),
    (
        _at(Phase.CONTROLLER_STEP),
        ProtocolError("kein Ergebnis-Trailer"),
        Phase.CONTROLLER_STEP,
        None,
    ),
    # Pruefung eines gecheckpointeten Ergebnisses: adaptive Wahl.
    (
        _reviewed(worker_attempt=1),
        ControllerTask("Naechster begrenzter Schnitt"),
        Phase.WORKER_STEP_PREPARE,
        None,
    ),
    (
        _reviewed(worker_attempt=1),
        ControllerChanges("Test fuer Y fehlt"),
        Phase.WORKER_STEP_PREPARE,
        None,
    ),
    (
        _reviewed(worker_attempt=1),
        ControllerNeedsDecision("Welche Ablage?"),
        Phase.WAITING_DECISION,
        None,
    ),
    (
        _reviewed(worker_attempt=1),
        ControllerEscalate("Werkzeug antwortet nicht"),
        Phase.PAUSED_INTERACTIVE,
        AgentEscalation,
    ),
    (
        _reviewed(worker_attempt=1),
        ControllerPass(),
        Phase.FREEZE_REVIEWED_RESULT,
        None,
    ),
    (
        _reviewed(worker_attempt=1),
        ProtocolError("kein Ergebnis-Trailer"),
        Phase.CONTROLLER_STEP,
        None,
    ),
    # Worker-Strecke.
    (
        _at(Phase.WORKER_STEP_PREPARE),
        WorkerInputsPrepared(),
        Phase.WORKER_STEP,
        None,
    ),
    (
        _at(Phase.WORKER_STEP),
        WorkerCompleted(),
        Phase.CAPTURE_STEP_RESULT,
        None,
    ),
    (
        _at(Phase.WORKER_STEP),
        WorkerNeedsDecision("Welches Schema?"),
        Phase.WAITING_DECISION,
        None,
    ),
    (
        _at(Phase.WORKER_STEP),
        WorkerEscalate("Zustand praktisch unklar"),
        Phase.PAUSED_INTERACTIVE,
        AgentEscalation,
    ),
    (
        _at(Phase.WORKER_STEP),
        WorkerProcessError("exit 137"),
        Phase.WORKER_STEP_PREPARE,
        None,
    ),
    (
        _at(Phase.WORKER_STEP),
        ProtocolError("unlesbare Ausgabe"),
        Phase.WORKER_STEP,
        None,
    ),
    (
        _at(Phase.CAPTURE_STEP_RESULT),
        _EFFECTIVE,
        Phase.CHECKPOINT,
        None,
    ),
    (
        _at(Phase.CAPTURE_STEP_RESULT),
        _EMPTY,
        Phase.WORKER_STEP_PREPARE,
        None,
    ),
    (
        _at(Phase.CHECKPOINT),
        CheckpointRecorded(),
        Phase.CONTROLLER_STEP,
        None,
    ),
    # Abschlussweg.
    (
        _at(Phase.FREEZE_REVIEWED_RESULT),
        ReviewedResultFrozen(),
        Phase.FINALIZE_HISTORY,
        None,
    ),
    (
        _at(Phase.FINALIZE_HISTORY),
        HistoryFinalized(),
        Phase.VERIFY_FINAL_RESULT,
        None,
    ),
    (
        _at(Phase.VERIFY_FINAL_RESULT),
        FinalResultVerified(ok=True),
        Phase.FAST_FORWARD_INTEGRATE,
        None,
    ),
    (
        _at(Phase.VERIFY_FINAL_RESULT),
        FinalResultVerified(ok=False),
        Phase.PAUSED_INTERACTIVE,
        MachineEscalation,
    ),
    (
        _at(Phase.FAST_FORWARD_INTEGRATE),
        IntegrationCompleted(ok=True),
        Phase.PASSED,
        None,
    ),
    (
        _at(Phase.FAST_FORWARD_INTEGRATE),
        IntegrationCompleted(ok=False),
        Phase.PAUSED_INTERACTIVE,
        MachineEscalation,
    ),
    (
        _at(Phase.FREEZE_REVIEWED_RESULT),
        FinalizationError("Referenz fehlt"),
        Phase.ERROR,
        None,
    ),
    (
        _at(Phase.FINALIZE_HISTORY),
        FinalizationError("Schreibfehler"),
        Phase.ERROR,
        None,
    ),
    (
        _at(Phase.VERIFY_FINAL_RESULT),
        FinalizationError("Baum nicht lesbar"),
        Phase.ERROR,
        None,
    ),
    (
        _at(Phase.FAST_FORWARD_INTEGRATE),
        FinalizationError("Remote weg"),
        Phase.ERROR,
        None,
    ),
    # Fortsetzung durch den Menschen: Entscheidung zurück zum
    # Controller, Pause zurück zum Fortsetzungspunkt (<history>).
    (
        _at(Phase.WAITING_DECISION),
        ResumeRequested(),
        Phase.CONTROLLER_STEP,
        None,
    ),
    (
        MachineState(
            Phase.PAUSED_INTERACTIVE, history=Phase.WORKER_STEP
        ),
        ResumeRequested(),
        Phase.WORKER_STEP,
        None,
    ),
    # Technischer Fehler einer Maschinenoperation: begrenzt am selben
    # Ort wiederholen.
    *(
        (_at(phase), ProcessError("bd nicht erreichbar"), phase, None)
        for phase in (
            Phase.CONTROLLER_STEP,
            Phase.WORKER_STEP_PREPARE,
            Phase.CAPTURE_STEP_RESULT,
        )
    ),
    (
        _at(Phase.CAPTURE_STEP_RESULT, process_retry=3),
        ProcessError("bd nicht erreichbar"),
        Phase.PAUSED_INTERACTIVE,
        MachineEscalation,
    ),
    # Schutzhalt des Ausführers aus jedem aktiven Zustand.
    *(
        (
            _at(phase),
            ExecutionStopped("Kontextgrenze erreicht"),
            Phase.PAUSED_INTERACTIVE,
            MachineEscalation,
        )
        for phase in Phase
        if phase not in STOPPED_PHASES
    ),
]


def test_resume_after_pause_survives_a_process_boundary():
    """History über den gespeicherten Laufzustand: speichern, neu
    laden, fortsetzen landet im Quellzustand."""
    paused = advance(
        _at(Phase.WORKER_STEP, protocol_attempt=1),
        ProtocolError("kein Trailer"),
        _TIGHT,
    )
    run = RunState("run-x", 1, paused.state, _TIGHT, paused.escalation)
    stored = json.loads(json.dumps(encode_run_state(run)))

    resumed = advance(
        decode_run_state(stored).state, ResumeRequested(), _TIGHT
    )

    assert paused.phase is Phase.PAUSED_INTERACTIVE
    assert resumed.phase is Phase.WORKER_STEP
    assert resumed.transition.target == "@history"


def test_pause_without_resume_point_is_rejected():
    with pytest.raises(InvalidTransition):
        advance(_at(Phase.PAUSED_INTERACTIVE), ResumeRequested())


def test_executor_facts_stop_changes_before_round_budget():
    """Fakten des Ausführers (Korrekturbudget, Stagnation) haben
    Vorrang vor den Rundengrenzen des Ablaufs."""
    for fact in ("changes_refused", "stagnation"):
        result = advance(
            _reviewed(worker_attempt=1),
            ControllerChanges("Test fehlt"),
            facts=frozenset({fact}),
        )
        assert result.phase is Phase.PAUSED_INTERACTIVE
        assert result.escalation.cause is (
            MachineEscalationCause.EXECUTION_GUARD
        )


@pytest.mark.parametrize(
    ("state", "event", "expected", "escalation_type"), _ALLOWED
)
def test_allowed_transition_table(
    state: MachineState,
    event: Event,
    expected: Phase,
    escalation_type: type | None,
):
    result = advance(state, event)
    assert result.phase is expected
    if escalation_type is None:
        assert result.escalation is None
    else:
        assert isinstance(result.escalation, escalation_type)


def test_table_covers_all_transitions():
    covered = {(s.phase, type(e)) for s, e, _, _ in _ALLOWED}
    declared = {
        (phase, event_type)
        for phase, row in TRANSITIONS.items()
        for event_type in row
    }
    assert covered == declared


_FORBIDDEN: list[tuple[MachineState, Event]] = [
    (_at(Phase.START), ControllerTask("Implementiere X")),
    (_at(Phase.START), ControllerPass()),
    # Ohne gecheckpointetes Ergebnis gibt es kein Qualitaetsurteil.
    (_at(Phase.CONTROLLER_STEP), ControllerPass()),
    (_at(Phase.CONTROLLER_STEP), ControllerChanges("Test fehlt")),
    (_at(Phase.CONTROLLER_STEP, worker_attempt=3), ControllerPass()),
    (_reviewed(worker_attempt=1), WorkerCompleted()),
    (_at(Phase.WORKER_STEP_PREPARE), WorkerCompleted()),
    (_at(Phase.WORKER_STEP), ControllerPass()),
    (_at(Phase.WORKER_STEP), CheckpointRecorded()),
    (_at(Phase.CAPTURE_STEP_RESULT), CheckpointRecorded()),
    (_at(Phase.CHECKPOINT), ControllerPass()),
    (_at(Phase.FREEZE_REVIEWED_RESULT), HistoryFinalized()),
    (_at(Phase.FAST_FORWARD_INTEGRATE), ReviewedResultFrozen()),
    (_at(Phase.VERIFY_FINAL_RESULT), IntegrationCompleted(ok=True)),
    (_at(Phase.WAITING_DECISION), CheckpointRecorded()),
    (_at(Phase.WAITING_DECISION), RunStarted()),
    (_at(Phase.PAUSED_INTERACTIVE), RunStarted()),
    (_at(Phase.PAUSED_INTERACTIVE), ControllerPass()),
    (_at(Phase.PASSED), RunStarted()),
    (_at(Phase.ERROR), RunStarted()),
]


@pytest.mark.parametrize(("state", "event"), _FORBIDDEN)
def test_forbidden_transition_is_rejected(
    state: MachineState, event: Event
):
    with pytest.raises(InvalidTransition) as excinfo:
        advance(state, event)
    assert excinfo.value.state is state
    assert excinfo.value.event is event
    assert type(event).__name__ in str(excinfo.value)


def test_initial_controller_step_cannot_judge():
    initial = _at(Phase.CONTROLLER_STEP)
    assert initial.checkpointed_result is False
    with pytest.raises(InvalidTransition):
        advance(initial, ControllerPass())
    with pytest.raises(InvalidTransition):
        advance(initial, ControllerChanges("Test fehlt"))


def test_only_checkpoint_makes_reviewable():
    after_run_start = advance(_at(Phase.START), RunStarted()).state
    assert after_run_start.checkpointed_result is False

    after_checkpoint = advance(
        _at(Phase.CHECKPOINT), CheckpointRecorded()
    ).state
    assert after_checkpoint.checkpointed_result is True

    after_task = advance(
        after_checkpoint, ControllerTask("Naechster Schnitt")
    ).state
    assert after_task.checkpointed_result is False


def test_pass_never_reaches_passed_directly():
    result = advance(_reviewed(worker_attempt=1), ControllerPass())
    assert result.phase is Phase.FREEZE_REVIEWED_RESULT
    assert result.phase is not Phase.PASSED


def test_passed_has_one_incoming_edge():
    reaching = [
        (state.phase, type(event))
        for state, event, target, _ in _ALLOWED
        if target is Phase.PASSED
    ]
    assert reaching == [
        (Phase.FAST_FORWARD_INTEGRATE, IntegrationCompleted)
    ]


_HAPPY_PATH: tuple[Event, ...] = (
    RunStarted(),
    ControllerTask("Implementiere X"),
    WorkerInputsPrepared(),
    WorkerCompleted(),
    _EFFECTIVE,
    CheckpointRecorded(),
    ControllerPass(),
    ReviewedResultFrozen(),
    HistoryFinalized(),
    FinalResultVerified(ok=True),
    IntegrationCompleted(ok=True),
)


def test_complete_run_walks_finalization():
    state = _at(Phase.START)
    walked = []
    for event in _HAPPY_PATH:
        state = advance(state, event).state
        walked.append(state.phase)
    assert walked == [
        Phase.CONTROLLER_STEP,
        Phase.WORKER_STEP_PREPARE,
        Phase.WORKER_STEP,
        Phase.CAPTURE_STEP_RESULT,
        Phase.CHECKPOINT,
        Phase.CONTROLLER_STEP,
        Phase.FREEZE_REVIEWED_RESULT,
        Phase.FINALIZE_HISTORY,
        Phase.VERIFY_FINAL_RESULT,
        Phase.FAST_FORWARD_INTEGRATE,
        Phase.PASSED,
    ]


@pytest.mark.parametrize(
    ("phase", "event"),
    [
        (Phase.VERIFY_FINAL_RESULT, FinalResultVerified(ok=False)),
        (Phase.FAST_FORWARD_INTEGRATE, IntegrationCompleted(ok=False)),
        (Phase.FREEZE_REVIEWED_RESULT, FinalizationError("kaputt")),
        (Phase.FINALIZE_HISTORY, FinalizationError("kaputt")),
        (Phase.VERIFY_FINAL_RESULT, FinalizationError("kaputt")),
        (Phase.FAST_FORWARD_INTEGRATE, FinalizationError("kaputt")),
    ],
)
def test_failed_finalization_not_passed(phase: Phase, event: Event):
    result = advance(_at(phase), event)
    assert result.phase is not Phase.PASSED
    assert result.state.is_stopped is True


def test_escalation_kinds_stay_distinct():
    agent = advance(
        _reviewed(worker_attempt=1),
        ControllerEscalate("Werkzeugverhalten unklar"),
    )
    machine = advance(
        _at(Phase.CONTROLLER_STEP, protocol_attempt=1),
        ProtocolError("kein Trailer"),
        _TIGHT,
    )

    assert isinstance(agent.escalation, AgentEscalation)
    assert not isinstance(agent.escalation, MachineEscalation)
    assert agent.escalation.cause == "Werkzeugverhalten unklar"
    assert agent.escalation.resume_point is Phase.CONTROLLER_STEP

    assert isinstance(machine.escalation, MachineEscalation)
    assert not isinstance(machine.escalation, AgentEscalation)
    assert (
        machine.escalation.cause
        is MachineEscalationCause.PROTOCOL_ATTEMPTS_EXHAUSTED
    )
    assert machine.escalation.resume_point is Phase.CONTROLLER_STEP


_EXHAUSTED: list[tuple[MachineState, Event, MachineEscalationCause]] = [
    (
        _reviewed(worker_attempt=1, changes_round=1),
        ControllerChanges("Immer noch unvollstaendig"),
        MachineEscalationCause.CHANGES_ROUNDS_EXHAUSTED,
    ),
    (
        _reviewed(worker_attempt=2),
        ControllerTask("Noch ein Schnitt"),
        MachineEscalationCause.WORKER_ATTEMPTS_EXHAUSTED,
    ),
    (
        _at(Phase.CONTROLLER_STEP, protocol_attempt=1),
        ProtocolError("kein Trailer"),
        MachineEscalationCause.PROTOCOL_ATTEMPTS_EXHAUSTED,
    ),
    (
        _at(Phase.WORKER_STEP, protocol_attempt=1),
        ProtocolError("kein Trailer"),
        MachineEscalationCause.PROTOCOL_ATTEMPTS_EXHAUSTED,
    ),
    (
        _at(Phase.WORKER_STEP, process_retry=1),
        WorkerProcessError("exit 137"),
        MachineEscalationCause.PROCESS_RETRIES_EXHAUSTED,
    ),
    (
        _at(Phase.CAPTURE_STEP_RESULT, changes_round=1),
        _EMPTY,
        MachineEscalationCause.EMPTY_RESULT_UNRESOLVED,
    ),
]


@pytest.mark.parametrize(("state", "event", "cause"), _EXHAUSTED)
def test_exhausted_limit_stops_cycle(
    state: MachineState,
    event: Event,
    cause: MachineEscalationCause,
):
    result = advance(state, event, _TIGHT)
    assert result.phase is Phase.PAUSED_INTERACTIVE
    assert isinstance(result.escalation, MachineEscalation)
    assert result.escalation.cause is cause
    assert result.escalation.resume_point is state.phase
    assert result.state.counters == state.counters


@pytest.mark.parametrize(
    ("state", "event", "expected"),
    [
        (
            _at(Phase.CONTROLLER_STEP),
            ControllerTask("Implementiere X"),
            Counters(worker_attempt=1),
        ),
        (
            _reviewed(worker_attempt=1),
            ControllerChanges("Test fehlt"),
            Counters(worker_attempt=2, changes_round=1),
        ),
        (
            _at(Phase.CAPTURE_STEP_RESULT, worker_attempt=1),
            _EMPTY,
            Counters(worker_attempt=2, changes_round=1),
        ),
        (
            _at(Phase.WORKER_STEP, worker_attempt=1),
            WorkerProcessError("exit 137"),
            Counters(worker_attempt=1, process_retry=1),
        ),
        (
            _at(Phase.CONTROLLER_STEP),
            ProtocolError("kein Trailer"),
            Counters(protocol_attempt=1),
        ),
    ],
)
def test_repeatable_step_consumes_limit(
    state: MachineState, event: Event, expected: Counters
):
    result = advance(state, event)
    assert result.state.counters == expected
    assert result.state.counters.run_total > state.counters.run_total


def test_empty_delta_is_not_a_success():
    result = advance(_at(Phase.CAPTURE_STEP_RESULT), _EMPTY)
    assert result.phase is not Phase.CHECKPOINT
    assert result.phase is Phase.WORKER_STEP_PREPARE
    assert result.state.checkpointed_result is False


_ADAPTIVE = Limits(
    protocol_attempts=1,
    worker_attempts=4,
    changes_rounds=1,
    process_retries=1,
)

_WORKER_CYCLE: tuple[Event, ...] = (
    WorkerInputsPrepared(),
    WorkerCompleted(),
    _EFFECTIVE,
    CheckpointRecorded(),
)


def _drive(
    state: MachineState, *events: Event, limits: Limits
) -> MachineState:
    """Fahre eine Folge angenommener Uebergaenge durch."""
    for event in events:
        state = advance(state, event, limits).state
    return state


def test_new_task_gets_fresh_rounds():
    """TASK B erhaelt neue Runden, bleibt aber laufweit begrenzt."""
    after_a = _drive(
        _at(Phase.START),
        RunStarted(),
        ControllerTask("TASK A"),
        *_WORKER_CYCLE,
        ControllerChanges("A: Test fehlt"),
        *_WORKER_CYCLE,
        limits=_ADAPTIVE,
    )
    # TASK A hat sein Rundenbudget aufgebraucht.
    assert after_a.counters.changes_round == 1
    assert after_a.counters.worker_attempt == 2
    blocked = advance(
        after_a, ControllerChanges("A: immer noch"), _ADAPTIVE
    )
    assert blocked.phase is Phase.PAUSED_INTERACTIVE
    assert (
        blocked.escalation.cause
        is MachineEscalationCause.CHANGES_ROUNDS_EXHAUSTED
    )

    # Ein neuer TASK ist trotzdem zulaessig und beginnt bei null.
    task_b = advance(after_a, ControllerTask("TASK B"), _ADAPTIVE)
    assert task_b.phase is Phase.WORKER_STEP_PREPARE
    assert task_b.state.counters.changes_round == 0
    assert task_b.state.counters.worker_attempt == 3

    # TASK B darf daher wieder korrigieren.
    after_b = _drive(task_b.state, *_WORKER_CYCLE, limits=_ADAPTIVE)
    corrected = advance(
        after_b, ControllerChanges("B: Test fehlt"), _ADAPTIVE
    )
    assert corrected.phase is Phase.WORKER_STEP_PREPARE
    assert corrected.state.counters.changes_round == 1
    assert corrected.state.counters.worker_attempt == 4

    # Das laufweite worker_attempt-Limit bindet weiterhin.
    exhausted = _drive(
        corrected.state, *_WORKER_CYCLE, limits=_ADAPTIVE
    )
    stopped = advance(exhausted, ControllerTask("TASK C"), _ADAPTIVE)
    assert stopped.phase is Phase.PAUSED_INTERACTIVE
    assert (
        stopped.escalation.cause
        is MachineEscalationCause.WORKER_ATTEMPTS_EXHAUSTED
    )


_LOOP_ANSWER: dict[Phase, Event] = {
    Phase.CONTROLLER_STEP: ControllerChanges(
        "Weiterhin unvollstaendig"
    ),
    Phase.WORKER_STEP_PREPARE: WorkerInputsPrepared(),
    Phase.WORKER_STEP: WorkerCompleted(),
    Phase.CAPTURE_STEP_RESULT: _EFFECTIVE,
    Phase.CHECKPOINT: CheckpointRecorded(),
}


def test_correction_loop_cannot_run_forever():
    state = advance(_at(Phase.START), RunStarted(), _TIGHT).state
    state = advance(
        state, ControllerTask("Implementiere X"), _TIGHT
    ).state

    escalation = None
    for _ in range(50):
        if state.is_stopped:
            break
        result = advance(state, _LOOP_ANSWER[state.phase], _TIGHT)
        escalation = result.escalation
        state = result.state

    assert state.phase is Phase.PAUSED_INTERACTIVE
    assert isinstance(escalation, MachineEscalation)
    assert escalation.cause in {
        MachineEscalationCause.CHANGES_ROUNDS_EXHAUSTED,
        MachineEscalationCause.WORKER_ATTEMPTS_EXHAUSTED,
    }
