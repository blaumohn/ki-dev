"""Ausführer des Planungsablaufs: fährt bis zum nächsten turn/ask.

``ki-dev step`` ist eine Projektion dieses Ausführers mit dem Adapter
``manual``: Die Schleife nimmt die Kante eines Startereignisses, führt
Maschinenzustände (``checks``) selbst aus und hält, sobald eine Sitzung
(``turn``) oder der Mensch (``ask``) an der Reihe ist. Welche Kante
gilt, entscheidet allein der Ablauf über :func:`~ki_dev.runner.
interpreter.bind`; was eine Maschinenoperation tut, liefert der Aufrufer
als benannte Implementierung (der Ausführer kennt step nicht).

Der Halt nennt Zustand, Operation und den genommenen Pfad. Daraus wählt
der Adapter die Vorlage (Vorlage am Übergang): dasselbe Review nach dem
Schreiben ist eine Erstübergabe, nach einer Korrektur eine
Folgenachricht.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace

from ki_dev.flow.model import Flow, FlowError, Transition
from ki_dev.runner.interpreter import Binding, BoundFlow, bind

TURN = "turn"
ASK = "ask"
CHECKS = "checks"
FULL_CHECKS = "full_checks"


@dataclass(frozen=True)
class PlanningContext:
    """Laufdaten für die Wächter: benannte Tatsachen (``full_checks``)
    und, nach einem Vorlauf, sein Ergebnis für die Übergabe."""

    facts: frozenset[str] = frozenset({FULL_CHECKS})
    outcome: object = None


@dataclass(frozen=True)
class Halt:
    """Wo der Lauf hält und auf welchem Weg er dorthin kam."""

    state: str
    operation: str | None
    path: tuple[Transition, ...] = ()
    context: PlanningContext = field(default_factory=PlanningContext)

    @property
    def via(self) -> Transition | None:
        """Letzte genommene Kante (``None`` ohne Startereignis)."""
        return self.path[-1] if self.path else None

    @property
    def entry(self) -> Transition | None:
        """Erste Kante: woher der Lauf in diese Runde kam."""
        return self.path[0] if self.path else None


MachineOperation = Callable[
    [str, PlanningContext], tuple[str, PlanningContext]
]
"""Führt eine Maschinenoperation im Zustand aus und liefert Ereignis und
neue Laufdaten."""


def bind_planning(flow: Flow) -> BoundFlow[PlanningContext]:
    return bind(
        flow,
        Binding(
            guards={
                FULL_CHECKS: lambda context: (
                    FULL_CHECKS in context.facts
                )
            },
            actions={},
            escalations=frozenset(),
            operations=frozenset({TURN, ASK, CHECKS}),
        ),
    )


def drive(
    bound: BoundFlow[PlanningContext],
    state: str,
    event: str | None,
    machine: Mapping[str, MachineOperation],
    context: PlanningContext | None = None,
) -> Halt:
    """Startereignis anwenden, Maschinenzustände fahren, beim nächsten
    turn/ask (oder Ende) halten."""
    context = context or PlanningContext()
    path: list[Transition] = []
    if event is not None:
        state = _take(bound, state, event, context, path)
    while True:
        operation = bound.operation(state, context)
        if operation is None:
            return Halt(state, None, tuple(path), context)
        if operation.do not in machine:
            return Halt(state, operation.do, tuple(path), context)
        event, context = machine[operation.do](state, context)
        state = _take(bound, state, event, context, path)


def _take(
    bound: BoundFlow[PlanningContext],
    state: str,
    event: str,
    context: PlanningContext,
    path: list[Transition],
) -> str:
    transition = bound.select(state, event, context)
    if transition is None:
        raise FlowError(f"Ereignis {event} in {state} nicht erlaubt")
    path.append(transition)
    return transition.target


def with_facts(
    context: PlanningContext, facts: frozenset[str], outcome: object
) -> PlanningContext:
    return replace(context, facts=facts, outcome=outcome)
