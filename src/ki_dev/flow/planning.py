"""Planungsablauf (``planning.toml``): Review-Semantik, Übergaben.

Fachliche Sicht auf den allgemeinen
:class:`~ki_dev.flow.model.Flow` für die Phasen map, graph,
materialize und implement: welche Befundklasse ein Review-Ereignis ist,
welches Urteil daraus folgt und welche Folgeschritte der Mensch als
Bote (Adapter ``manual``, ``ki-dev step``) erhält.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ki_dev.flow.model import (
    Flow,
    FlowError,
    Transition,
    load_flow,
)

NAME = "planning"
FILE_NAME = f"{NAME}.toml"


@dataclass(frozen=True)
class PlanningFlow:
    flow: Flow

    def outgoing(self, state: str) -> tuple[Transition, ...]:
        return self.flow.outgoing(state)

    def target_after(
        self,
        state: str,
        event: str,
        facts: frozenset[str] = frozenset(),
    ) -> str:
        """Ziel der ersten Kante (state, event), deren Wächter nach
        ``facts`` gelten (benannte Tatsachen, ``!`` verneint)."""
        for transition in self.flow.candidates(state, event):
            if _holds(transition.cond, facts):
                return transition.target
        raise FlowError(f"keine Kante {state} --{event}-->")

    def allows(
        self,
        state: str,
        event: str,
        facts: frozenset[str] = frozenset(),
    ) -> bool:
        """Ob ``event`` in ``state`` bei diesen Tatsachen erlaubt
        ist."""
        return any(
            _holds(t.cond, facts)
            for t in self.flow.candidates(state, event)
        )

    def hint_lines(
        self,
        state: str,
        bead: str,
        events: Iterable[str] | None = None,
    ) -> list[str]:
        """Übergabe an den Menschen als Boten: Folgeschritte aus dem
        Ablauf mit eingesetzter Bead-ID; ``events`` beschränkt sie auf
        die Übergänge eines Urteils."""
        wanted = None if events is None else set(events)
        lines = [
            f"Hinweis für den Menschen: Zustand {state}; Folgeschritte "
            f"laut {FILE_NAME} (Adapter manual, du trägst sie weiter):"
        ]
        for transition in self.outgoing(state):
            if wanted is not None and transition.event not in wanted:
                continue
            command = (transition.hint or "").replace("{bead}", bead)
            lines.append(
                f"- {transition.event} → {transition.target}: {command}"
            )
        return lines

    def class_lines(self) -> list[str]:
        """Befundklassen für Review-Rollen, in Vorrangreihenfolge."""
        classes = self.flow.finding_classes
        parts = [
            f"{name} = {classes[name].text} ({classes[name].verdict})"
            for name in self.flow.priority
        ]
        return [
            "Befundklassen: " + "; ".join(parts) + ".",
            "Nenne je Befund seine Klasse; das Urteil folgt der "
            f"stärksten Klasse ({' > '.join(self.flow.priority)}), "
            "ohne Befund PASS.",
        ]


def _holds(cond: Iterable[str], facts: frozenset[str]) -> bool:
    return all(
        (name.removeprefix("!") in facts) != name.startswith("!")
        for name in cond
    )


def load_planning_flow() -> PlanningFlow:
    """Mitgelieferten Planungsablauf laden und prüfen; er muss
    Befundklassen und für jeden Übergang einen Befehl tragen."""
    flow = load_flow(NAME)
    if not flow.finding_classes:
        raise FlowError(f"{FILE_NAME}: befundklasse fehlt")
    for index, transition in enumerate(flow.transitions):
        if transition.hint is None:
            raise FlowError(
                f"{FILE_NAME}: transition.{index}.hint fehlt"
            )
    return PlanningFlow(flow)
