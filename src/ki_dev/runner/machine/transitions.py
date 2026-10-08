"""Reine Übergangsentscheidung: Interpreter über ``flow/delivery.toml``.

:func:`advance` ist die einzige öffentliche Entscheidung. Sie bildet
``(Zustand, Ereignis)`` deterministisch auf einen Folgezustand ab oder
weist den Übergang mit :class:`InvalidTransition` sichtbar ab. Es gibt
keinen stillen Rücksprung und keinen stillen Standardfall.

Welche Kante gilt, steht nur im Ablauf. Dieses Modul bindet dessen
Vokabular: was ein Wächter prüft (:data:`_WAECHTER`) und was eine
Aktion am Zustand ändert (:data:`_AKTIONEN`). Beim Import prüft
:func:`~ki_dev.runner.interpreter.binde`, dass beide Seiten genau
dieselben Namen kennen.

Die Begrenztheit ruht auf den laufweit monotonen Zählern in
``Counters.run_total``: jede rücklaufende Kante des Ablaufs trägt eine
Aktion, die ``worker_attempt``, ``process_retry`` oder
``protocol_attempt`` erhöht, und ist durch den passenden ``*_frei``-
Wächter begrenzt. ``changes_round`` begrenzt zusätzlich die Korrekturen
innerhalb genau eines TASK; ``task_beginnen`` setzt ihn bewusst zurück.

Zwei Wächter sind Fakten des Ausführers (``korrekturen_abgelehnt``,
``stagnation``): sie hängen an Laufdaten außerhalb dieses Zustands
(Verbrauchsbuch, Beanstandungsverlauf). Der Ausführer ermittelt sie
und übergibt sie als ``fakten``; die Entscheidung, was daraus folgt,
bleibt im Ablauf.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ki_dev.deltas import StepDeltaAssessment
from ki_dev.flow.model import HISTORY, AblaufError
from ki_dev.runner.interpreter import (
    Bindung,
    GebundenerAblauf,
    binde,
)

from .contract import (
    BAU,
    DEFAULT_LIMITS,
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
    fakten: frozenset[str] = field(default_factory=frozenset)


def advance(
    state: MachineState,
    event: Event,
    limits: Limits = DEFAULT_LIMITS,
    *,
    fakten: frozenset[str] = frozenset(),
) -> TransitionResult:
    """Entscheide den Folgezustand oder weise den Übergang ab."""
    step = _Step(state=state, event=event, limits=limits, fakten=fakten)
    if state.phase.value not in BAU.zustaende:
        raise InvalidTransition(state, event)
    uebergang = BAU_GEBUNDEN.waehle(
        state.phase.value, event.ereignis, step
    )
    if uebergang is None:
        raise InvalidTransition(state, event)
    target = _target(step, uebergang.nach)
    moved = state
    for name in uebergang.aktion:
        moved = _AKTIONEN[name](moved)
    return TransitionResult(
        state=moved.moved_to(target),
        escalation=_escalation(step, uebergang.eskalation),
    )


def _target(step: _Step, nach: str) -> Phase:
    if nach != HISTORY:
        return Phase(nach)
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


_WAECHTER: dict[str, Callable[[_Step], bool]] = {
    "geprueftes_ergebnis": lambda s: s.state.checkpointed_result,
    "korrekturrunden_frei": lambda s: (
        _counters(s).changes_round < s.limits.changes_rounds
    ),
    "bauversuche_frei": lambda s: (
        _counters(s).worker_attempt < s.limits.worker_attempts
    ),
    "protokollversuche_frei": lambda s: (
        _counters(s).protocol_attempt < s.limits.protocol_attempts
    ),
    "prozessversuche_frei": lambda s: (
        _counters(s).process_retry < s.limits.process_retries
    ),
    "delta_wirksam": lambda s: (
        s.event.assessment is StepDeltaAssessment.EFFECTIVE
    ),
    "ergebnis_ok": lambda s: s.event.ok,
    "korrekturen_abgelehnt": lambda s: (
        "korrekturen_abgelehnt" in s.fakten
    ),
    "stagnation": lambda s: "stagnation" in s.fakten,
}


# --- Vokabular: Kantenaktionen ----------------------------------------


def _with_counters(
    change: Callable[[Counters], Counters],
) -> Callable[[MachineState], MachineState]:
    return lambda state: state.moved_to(
        state.phase, counters=change(state.counters)
    )


_AKTIONEN: dict[str, Callable[[MachineState], MachineState]] = {
    "task_beginnen": _with_counters(Counters.started_task),
    "korrektur_beginnen": _with_counters(Counters.started_correction),
    "protokoll_wiederholen": _with_counters(Counters.retried_protocol),
    "prozess_wiederholen": _with_counters(Counters.retried_process),
    "ergebnis_festhalten": lambda state: state.moved_to(
        state.phase, checkpointed_result=True
    ),
    "ergebnis_verwerfen": lambda state: state.moved_to(
        state.phase, checkpointed_result=False
    ),
}

_ESKALATIONEN = frozenset(
    {"agent", *(cause.value for cause in MachineEscalationCause)}
)

# Operationen führt die Laufzeit aus; hier nur ihre Namen, damit der
# Ablauf auch ohne Laufzeit vollständig gebunden und geprüft ist.
OPERATIONEN = frozenset(BAU.vokabular.operationen)

BAU_GEBUNDEN: GebundenerAblauf[_Step] = binde(
    BAU,
    Bindung(
        waechter=_WAECHTER,
        aktionen=_AKTIONEN,
        eskalationen=_ESKALATIONEN,
        operationen=OPERATIONEN,
    ),
)


def _event_types() -> dict[str, type[Event]]:
    pending = list(Event.__subclasses__())
    found: dict[str, type[Event]] = {}
    while pending:
        cls = pending.pop()
        found[cls.ereignis] = cls
        pending.extend(cls.__subclasses__())
    return found


EVENT_TYPES = _event_types()
"""Ereignisname im Ablauf → typisierte Ereignisklasse."""

if set(EVENT_TYPES) != set(BAU.vokabular.ereignisse):
    raise AblaufError(
        "delivery.toml: Ereignisse passen nicht zu machine.Event"
    )

_TRANSITIONS: dict[Phase, dict[type[Event], tuple[str, ...]]] = {}
"""Abgeleitete Sicht für Tests: welche Ereignistypen je Zustand
überhaupt eine Kante haben (Ziele der Kandidaten in Prüfreihenfolge)."""
for _t in BAU.uebergaenge:
    _row = _TRANSITIONS.setdefault(Phase(_t.von), {})
    _type = EVENT_TYPES[_t.bei]
    _row[_type] = (*_row.get(_type, ()), _t.nach)


def operation(
    state: MachineState, limits: Limits = DEFAULT_LIMITS
) -> str | None:
    """Operation, die der Ausführer in ``state`` auszuführen hat
    (Moore-Ausgabe des Ablaufs); ``None`` für Halt und Ende."""
    step = _Step(state=state, event=Event(), limits=limits)
    chosen = BAU_GEBUNDEN.operation(state.phase.value, step)
    return None if chosen is None else chosen.tue
