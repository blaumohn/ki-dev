"""Abläufe auf dem Review-Muster (``flow/patterns/review.toml``).

Fachliche Sicht auf den allgemeinen :class:`~ki_dev.flow.model.Flow`:
welche Befundklasse ein Review-Ereignis ist, welches Urteil daraus
folgt und welche Folgeschritte der Mensch als Bote (Executor
``manual``, ``ki-dev step``) erhält.
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

TEMPLATES = "review"
"""Vorlagensatz der Review-Abläufe (``flow/templates/review``)."""


@dataclass(frozen=True)
class ReviewFlow:
    flow: Flow

    @property
    def file(self) -> str:
        return f"{self.flow.name}.toml"

    def state_of(self, kind: str) -> str:
        """Der eine Zustand dieser Art (``review``, ``correction``)."""
        found = [
            state.id
            for state in self.flow.states.values()
            if state.kind == kind
        ]
        if len(found) != 1:
            raise FlowError(
                f"{self.file}: {len(found)} Zustände der Art {kind}"
            )
        return found[0]

    def binds(self, operation: str) -> bool:
        """Ob ein Zustand die Katalogoperation ``operation`` nutzt."""
        return any(
            binding.do == operation
            for binding in self.flow.bindings.values()
        )

    def outgoing(self, state: str) -> tuple[Transition, ...]:
        return self.flow.outgoing(state)

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
            f"laut {self.file} (Adapter manual, du trägst sie weiter):"
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


def load_review_flow(name: str) -> ReviewFlow:
    """Mitgelieferten Ablauf laden und prüfen; er muss Befundklassen
    und für jeden Übergang einen Befehl tragen."""
    flow = load_flow(name)
    if not flow.finding_classes:
        raise FlowError(f"{name}.toml: befundklasse fehlt")
    for index, transition in enumerate(flow.transitions):
        if transition.hint is None:
            raise FlowError(
                f"{name}.toml: transition.{index}.hint fehlt"
            )
    return ReviewFlow(flow)
