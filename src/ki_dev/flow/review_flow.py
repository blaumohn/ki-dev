"""Abläufe auf dem Review-Muster (``flow/patterns/review.toml``).

Fachliche Sicht auf den allgemeinen :class:`~ki_dev.flow.model.Flow`:
welche Befundklasse ein Review-Ereignis ist, welches Urteil daraus
folgt und welche Folgeschritte der Mensch als Bote (Executor
``manual``, ``ki-dev -f ABLAUF step``) erhält.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib.resources import files

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


def review_flow_files() -> dict[str, str]:
    """Phase (Start) → Name der mitgelieferten Abläufe auf dem
    Review-Muster, nach Phase sortiert; was es gibt, sagen die Dateien
    unter ``flow/``."""
    found = {}
    for item in files("ki_dev.flow").iterdir():
        if not item.name.endswith(".toml"):
            continue
        raw = tomllib.loads(item.read_text(encoding="utf-8"))
        if "ki_dev:review" in raw.get("pattern_catalog", ()):
            found[raw["start"]] = raw["name"]
    return dict(sorted(found.items()))


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
