"""Reine Übergangsentscheidung: Interpreter über ``flow/delivery.toml``.

:func:`advance` ist die einzige öffentliche Entscheidung. Sie bildet
``(Zustand, Ereignis)`` deterministisch auf einen Folgezustand ab oder
weist den Übergang mit :class:`InvalidTransition` sichtbar ab. Es gibt
keinen stillen Rücksprung und keinen stillen Standardfall.

Welche Kante gilt, steht nur im Ablauf. Dieses Modul bindet dessen
Vokabular: was ein Wächter prüft (:data:`_GUARDS`) und was eine
Aktion am Zustand ändert (:data:`_ACTIONS`). Beim Import prüft
:func:`~ki_dev.runner.interpreter.bind`, dass beide Seiten genau
dieselben Namen kennen.

Die Begrenztheit ruht auf den laufweit monotonen Zählern in
``Counters.run_total``: jede rücklaufende Kante des Ablaufs trägt eine
Aktion, die ``worker_attempt``, ``process_retry`` oder
``protocol_attempt`` erhöht, und ist durch den passenden ``*_left``-
Wächter begrenzt. ``changes_round`` begrenzt zusätzlich die Korrekturen
innerhalb genau eines TASK; ``begin_task`` setzt ihn bewusst zurück.

Zwei Wächter sind Fakten des Ausführers (``changes_refused``,
``stagnation``): sie hängen an Laufdaten außerhalb dieses Zustands
(Verbrauchsbuch, Beanstandungsverlauf). Der Ausführer ermittelt sie
und übergibt sie als ``facts``; die Entscheidung, was daraus folgt,
bleibt im Ablauf.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ki_dev.deltas import StepDeltaAssessment
from ki_dev.flow.model import HISTORY, FlowError
from ki_dev.runner.interpreter import (
    Binding,
    BoundFlow,
    bind,
)

from .contract import (
    DEFAULT_LIMITS,
    DELIVERY,
    AgentEscalation,
    Counters,
    Event,
    InvalidTransition,
    Limits,
    MachineEscalation,
    MachineEscalationCause,
    MachineState,
    Phase,
    ResumeRequested,
    TransitionResult,
)


@dataclass(frozen=True)
class _Step:
    """Vollständige Eingabe genau einer Übergangsentscheidung."""

    state: MachineState
    event: Event
    limits: Limits
    facts: frozenset[str] = field(default_factory=frozenset)


def advance(
    state: MachineState,
    event: Event,
    limits: Limits = DEFAULT_LIMITS,
    *,
    facts: frozenset[str] = frozenset(),
) -> TransitionResult:
    """Entscheide den Folgezustand oder weise den Übergang ab."""
    step = _Step(state=state, event=event, limits=limits, facts=facts)
    if state.phase.value not in DELIVERY.states:
        raise InvalidTransition(state, event)
    transition = DELIVERY_BOUND.select(
        state.phase.value, event.flow_event, step
    )
    if transition is None:
        raise InvalidTransition(state, event)
    target = _target(step, transition.target)
    moved = state
    for name in transition.actions:
        moved = _ACTIONS[name](moved)
    return TransitionResult(
        state=moved.moved_to(target),
        escalation=_escalation(step, transition.escalation),
    )


def _target(step: _Step, target: str) -> Phase:
    if target != HISTORY:
        return Phase(target)
    event = step.event
    if (
        not isinstance(event, ResumeRequested)
        or event.resume_point is None
    ):
        raise InvalidTransition(step.state, step.event)
    return event.resume_point


def _escalation(
    step: _Step, cause: str | None
) -> AgentEscalation | MachineEscalation | None:
    if cause is None:
        return None
    resume_point = step.state.phase
    if cause == "agent":
        return AgentEscalation(
            cause=step.event.cause, resume_point=resume_point
        )
    return MachineEscalation(
        cause=MachineEscalationCause(cause), resume_point=resume_point
    )


# --- Vokabular: Wächter -----------------------------------------------


def _counters(step: _Step) -> Counters:
    return step.state.counters


_GUARDS: dict[str, Callable[[_Step], bool]] = {
    "checked_result": lambda s: s.state.checkpointed_result,
    "changes_rounds_left": lambda s: (
        _counters(s).changes_round < s.limits.changes_rounds
    ),
    "worker_attempts_left": lambda s: (
        _counters(s).worker_attempt < s.limits.worker_attempts
    ),
    "protocol_attempts_left": lambda s: (
        _counters(s).protocol_attempt < s.limits.protocol_attempts
    ),
    "process_retries_left": lambda s: (
        _counters(s).process_retry < s.limits.process_retries
    ),
    "delta_effective": lambda s: (
        s.event.assessment is StepDeltaAssessment.EFFECTIVE
    ),
    "result_ok": lambda s: s.event.ok,
    "changes_refused": lambda s: (
        "changes_refused" in s.facts
    ),
    "stagnation": lambda s: "stagnation" in s.facts,
}


# --- Vokabular: Kantenaktionen ----------------------------------------


def _with_counters(
    change: Callable[[Counters], Counters],
) -> Callable[[MachineState], MachineState]:
    return lambda state: state.moved_to(
        state.phase, counters=change(state.counters)
    )


_ACTIONS: dict[str, Callable[[MachineState], MachineState]] = {
    "begin_task": _with_counters(Counters.started_task),
    "begin_correction": _with_counters(Counters.started_correction),
    "retry_protocol": _with_counters(Counters.retried_protocol),
    "retry_process": _with_counters(Counters.retried_process),
    "keep_result": lambda state: state.moved_to(
        state.phase, checkpointed_result=True
    ),
    "drop_result": lambda state: state.moved_to(
        state.phase, checkpointed_result=False
    ),
}

_ESKALATIONEN = frozenset(
    {"agent", *(cause.value for cause in MachineEscalationCause)}
)

# Operationen führt die Laufzeit aus; hier nur ihre Namen, damit der
# Ablauf auch ohne Laufzeit vollständig gebunden und geprüft ist.
OPERATIONEN = frozenset(DELIVERY.vocabulary.operations)

DELIVERY_BOUND: BoundFlow[_Step] = bind(
    DELIVERY,
    Binding(
        guards=_GUARDS,
        actions=_ACTIONS,
        escalations=_ESKALATIONEN,
        operations=OPERATIONEN,
    ),
)


def _event_types() -> dict[str, type[Event]]:
    pending = list(Event.__subclasses__())
    found: dict[str, type[Event]] = {}
    while pending:
        cls = pending.pop()
        found[cls.flow_event] = cls
        pending.extend(cls.__subclasses__())
    return found


EVENT_TYPES = _event_types()
"""Ereignisname im Ablauf → typisierte Ereignisklasse."""

if set(EVENT_TYPES) != set(DELIVERY.vocabulary.events):
    raise FlowError(
        "delivery.toml: Ereignisse passen nicht zu machine.Event"
    )

_TRANSITIONS: dict[Phase, dict[type[Event], tuple[str, ...]]] = {}
"""Abgeleitete Sicht für Tests: welche Ereignistypen je Zustand
überhaupt eine Kante haben (Ziele der Kandidaten in Prüfreihenfolge)."""
for _t in DELIVERY.transitions:
    _row = _TRANSITIONS.setdefault(Phase(_t.source), {})
    _type = EVENT_TYPES[_t.event]
    _row[_type] = (*_row.get(_type, ()), _t.target)


def operation(
    state: MachineState, limits: Limits = DEFAULT_LIMITS
) -> str | None:
    """Operation, die der Ausführer in ``state`` auszuführen hat
    (Moore-Ausgabe des Ablaufs); ``None`` für Halt und Ende."""
    step = _Step(state=state, event=Event(), limits=limits)
    chosen = DELIVERY_BOUND.operation(state.phase.value, step)
    return None if chosen is None else chosen.do
