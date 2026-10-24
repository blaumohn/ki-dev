"""Ops des Umsetzungsablaufs und reine Übergangsentscheidung.

Welche Kante gilt, wählt python-statemachine aus ``[statechart]`` von
``flow/implement.toml`` (:mod:`ki_dev.fsm`). Dieses Modul liefert nur
das Vokabular, das die Datei beim Namen nennt: was ein Wächter prüft
und was eine Aktion am Modell ändert (:class:`ImplementModel`). Beim
Import prüft :func:`ki_dev.fsm.bind`, dass beide Seiten genau dieselben
Namen kennen.

:func:`advance` bildet ``(Zustand, Ereignis)`` deterministisch auf
einen Folgezustand ab oder weist den Übergang mit
:class:`InvalidTransition` sichtbar ab. Es gibt keinen stillen
Rücksprung und keinen stillen Standardfall.

Die Begrenztheit ruht auf den laufweit monotonen Zählern in
``Counters.run_total``: jede rücklaufende Kante des Ablaufs trägt eine
Aktion, die ``worker_attempt``, ``process_retry`` oder
``protocol_attempt`` erhöht, und ist durch den passenden ``*_left``-
Wächter begrenzt. ``changes_round`` begrenzt zusätzlich die Korrekturen
innerhalb genau eines TASK; ``begin_task`` setzt ihn bewusst zurück.

Drei Wächter sind Fakten des Ausführers (``changes_refused``,
``stagnation``, ``checks_failed``): sie hängen an Laufdaten außerhalb
dieses Zustands (Verbrauchsbuch, Beanstandungsverlauf, Prüfungen der
Runde). Der Ausführer ermittelt sie und übergibt sie als ``facts``; die
Entscheidung, was daraus folgt, bleibt im Ablauf.
"""

from __future__ import annotations

from ki_dev.deltas import StepDeltaAssessment
from ki_dev.flow.model import FlowError, Operation
from ki_dev.flow.statechart import ESCALATION_EVENT
from ki_dev.fsm import (
    Durable,
    TransitionNotAllowed,
    bind,
    configuration_of,
)

from .contract import (
    DEFAULT_LIMITS,
    IMPLEMENT,
    AgentEscalation,
    Event,
    InvalidTransition,
    Limits,
    MachineEscalation,
    MachineEscalationCause,
    MachineState,
    Phase,
    TransitionResult,
)

AGENT_CAUSE = "agent"
"""Eskalationsursache, die der Agent selbst meldet (freier Text)."""


class ImplementModel:
    """Modell der Ablauf-Maschine: Zähler, Ergebnisflag und die Namen,
    die ``[statechart]`` als Wächter (``cond``/``unless``) und Aktion
    (``on``) nennt. Callbacks sind rein; ``payload`` ist das gesendete
    Ereignis."""

    def __init__(
        self,
        state: MachineState,
        limits: Limits = DEFAULT_LIMITS,
        facts: frozenset[str] = frozenset(),
    ) -> None:
        self.counters = state.counters
        self.checkpointed_result = state.checkpointed_result
        self.limits = limits
        self.facts = facts
        self.escalation: str | None = None

    # --- Wächter ------------------------------------------------------

    def checked_result(self) -> bool:
        """Ein Worker-Ergebnis ist gecheckpointet."""
        return self.checkpointed_result

    def changes_rounds_left(self) -> bool:
        return self.counters.changes_round < self.limits.changes_rounds

    def worker_attempts_left(self) -> bool:
        return (
            self.counters.worker_attempt < self.limits.worker_attempts
        )

    def protocol_attempts_left(self) -> bool:
        return (
            self.counters.protocol_attempt
            < self.limits.protocol_attempts
        )

    def process_retries_left(self) -> bool:
        return (
            self.counters.process_retry < self.limits.process_retries
        )

    def delta_effective(self, payload: Event) -> bool:
        """Schrittdelta hat beobachtete Wirkung."""
        return payload.assessment is StepDeltaAssessment.EFFECTIVE

    def result_ok(self, payload: Event) -> bool:
        """Abschlussprüfung bzw. Integration gelungen."""
        return payload.ok

    def changes_refused(self) -> bool:
        """Fakt des Ausführers: Korrekturbudget des Laufs erschöpft."""
        return "changes_refused" in self.facts

    def stagnation(self) -> bool:
        """Fakt des Ausführers: gleiches Kriterium wiederholt
        beanstandet."""
        return "stagnation" in self.facts

    def checks_failed(self) -> bool:
        """Fakt des Ausführers: eine Prüfung aus dem Profil ist in der
        geprüften Runde rot."""
        return "checks_failed" in self.facts

    # --- Aktionen -----------------------------------------------------

    def begin_task(self) -> None:
        """worker_attempt + 1, changes_round = 0."""
        self.counters = self.counters.started_task()

    def begin_correction(self) -> None:
        """worker_attempt + 1, changes_round + 1."""
        self.counters = self.counters.started_correction()

    def reset_corrections(self) -> None:
        """changes_round = 0 nach einer Entscheidung des Menschen."""
        self.counters = self.counters.decided()

    def retry_protocol(self) -> None:
        self.counters = self.counters.retried_protocol()

    def retry_process(self) -> None:
        self.counters = self.counters.retried_process()

    def keep_result(self) -> None:
        self.checkpointed_result = True

    def drop_result(self) -> None:
        self.checkpointed_result = False

    def record_escalation(self, event: object) -> None:
        """Empfänger von ``raise escalation.<ursache>``."""
        self.escalation = str(event).removeprefix(
            f"{ESCALATION_EVENT}."
        )


OPERATION_GUARDS = frozenset(
    name.removeprefix("!")
    for state in IMPLEMENT.states.values()
    for operation in state.operations
    for name in operation.cond
)
"""Wächter, die die Fachschicht nennt (Wahl der Operation), nicht der
``[statechart]``."""

IMPLEMENT_CHART = bind(
    IMPLEMENT.statechart, ImplementModel, also=OPERATION_GUARDS
)

if set(IMPLEMENT.vocabulary.escalations) != {
    AGENT_CAUSE,
    *(cause.value for cause in MachineEscalationCause),
}:
    raise FlowError(
        "implement.toml: Eskalationen passen nicht zu "
        "MachineEscalationCause"
    )


def advance(
    state: MachineState,
    event: Event,
    limits: Limits = DEFAULT_LIMITS,
    *,
    facts: frozenset[str] = frozenset(),
) -> TransitionResult:
    """Entscheide den Folgezustand oder weise den Übergang ab (der
    Ablauf allein, ohne Lauf)."""
    model = ImplementModel(state, limits, facts)
    machine = Durable(IMPLEMENT_CHART, model, _record(state))
    return step(machine, model, state, event)


def step(
    machine: Durable,
    model: ImplementModel,
    state: MachineState,
    event: Event,
) -> TransitionResult:
    """Ein Ereignis des Ablaufs an ``machine`` senden: den Ablauf allein
    oder den Lauf, in dem er eine Region ist (``model`` ist dann das
    gemeinsame Modell). ``state`` ist der Stand vor dem Ereignis."""
    try:
        taken = machine.send(event.flow_event, payload=event)
    except TransitionNotAllowed:
        raise InvalidTransition(state, event) from None
    transition = IMPLEMENT.edge(
        taken.owner, taken.index, state.phase.value
    )
    moved = MachineState(
        phase=phase_of(machine.configuration),
        counters=model.counters,
        checkpointed_result=model.checkpointed_result,
    )
    return TransitionResult(
        state=moved,
        escalation=_escalation(state.phase, event, model.escalation),
        transition=transition,
    )


def phase_of(configuration: list[str]) -> Phase:
    """Innerster Ablaufzustand einer Konfiguration (auch einer, in der
    der Ablauf eine von mehreren Regionen ist)."""
    (phase,) = (sid for sid in configuration if sid in _PHASES)
    return Phase(phase)


_PHASES = frozenset(phase.value for phase in Phase)


def _record(state: MachineState) -> dict[str, object]:
    """Datensatz der Bibliothek zu einem Maschinenzustand."""
    return {
        "state": configuration_of(IMPLEMENT_CHART, state.phase.value),
        "history": {},
    }


def _escalation(
    phase: Phase, event: Event, cause: str | None
) -> AgentEscalation | MachineEscalation | None:
    """Eskalation aus dem Ereignis: Ursache laut Ablauf, Fortsetzung
    am Quellzustand."""
    if cause is None:
        return None
    if cause == AGENT_CAUSE:
        return AgentEscalation(cause=event.cause, resume_point=phase)
    return MachineEscalation(
        cause=MachineEscalationCause(cause), resume_point=phase
    )


def operation_of(
    state: MachineState, limits: Limits = DEFAULT_LIMITS
) -> Operation | None:
    """Operation, die der Ausführer in ``state`` auszuführen hat
    (Moore-Ausgabe des Ablaufs), mit ihren Daten für den Lauf;
    ``None`` für Halt und Ende."""
    model = ImplementModel(state, limits)
    return IMPLEMENT.operation(
        state.phase.value, lambda name: getattr(model, name)()
    )


def operation(
    state: MachineState, limits: Limits = DEFAULT_LIMITS
) -> str | None:
    """Name der Operation in ``state`` (:func:`operation_of`)."""
    chosen = operation_of(state, limits)
    return None if chosen is None else chosen.do


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

if set(EVENT_TYPES) != set(IMPLEMENT.vocabulary.events):
    raise FlowError(
        "implement.toml: Ereignisse passen nicht zu machine.Event"
    )
