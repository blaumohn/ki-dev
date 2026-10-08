"""Generischer Interpreter eines deklarativen Ablaufs.

Der Ausführer kennt keine Topologie. Er bekommt einen geprüften
:class:`~ki_dev.flow.model.Ablauf`, bindet dessen Vokabular an
Implementierungen (:class:`Binding`) und wählt zu (Zustand, Ereignis)
den ersten Übergang, dessen Wächter gelten. Welche Wirkung eine Aktion
hat, entscheidet die Bindung; welche Kante gilt, allein der Ablauf.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TypeVar

from ki_dev.flow.model import (
    Flow,
    FlowError,
    Operation,
    Transition,
)

K = TypeVar("K")
"""Kontext der Wächter (Zustand, Ereignis, Grenzen, …)."""


@dataclass(frozen=True)
class Binding[K]:
    """Implementierung des Vokabulars eines Ablaufs.

    ``guards`` und ``actions`` müssen genau die im Ablauf
    deklarierten Namen abdecken; ``escalations`` und ``operations``
    nennen die Namen, die der Ausführer versteht."""

    guards: Mapping[str, Callable[[K], bool]]
    actions: Mapping[str, object]
    escalations: frozenset[str]
    operations: frozenset[str]


@dataclass(frozen=True)
class BoundFlow[K]:
    flow: Flow
    binding: Binding[K]

    def select(
        self, state: str, flow_event: str, context: K
    ) -> Transition | None:
        """Erster Kandidat, dessen Wächter gelten; sonst ``None``."""
        for transition in self.flow.candidates(state, flow_event):
            if self.holds(transition.cond, context):
                return transition
        return None

    def operation(self, state: str, context: K) -> Operation | None:
        """Was beim Betreten von ``state`` auszuführen ist (Moore)."""
        for operation in self.flow.state(state).operations:
            if self.holds(operation.cond, context):
                return operation
        return None

    def holds(self, guards: Iterable[str], context: K) -> bool:
        return all(self._one(name, context) for name in guards)

    def _one(self, name: str, context: K) -> bool:
        negated = name.startswith("!")
        value = self.binding.guards[name.removeprefix("!")](context)
        return not value if negated else value


def bind[K](
    flow: Flow, binding: Binding[K]
) -> BoundFlow[K]:
    """Prüfen, dass Ablauf und Ausführer dasselbe Vokabular sprechen."""
    vocabulary = flow.vocabulary
    for kind, declared, implemented in (
        ("Wächter", vocabulary.guards, binding.guards),
        ("Aktionen", vocabulary.actions, binding.actions),
        ("Eskalationen", vocabulary.escalations, binding.escalations),
        ("Operationen", vocabulary.operations, binding.operations),
    ):
        missing = sorted(set(declared) - set(implemented))
        foreign = sorted(set(implemented) - set(declared))
        if missing or foreign:
            raise FlowError(
                f"{flow.name}.toml: {kind} passen nicht zum Ausführer "
                f"(fehlt: {', '.join(missing) or '-'}; "
                f"nicht deklariert: {', '.join(foreign) or '-'})"
            )
    return BoundFlow(flow, binding)
