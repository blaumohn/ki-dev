"""Ausführer des Planungsablaufs: LangGraph-Thread je Bead.

``ki-dev step`` ist eine Projektion dieses Ausführers mit dem Adapter
``manual``. Der Graph entsteht mit demselben Übersetzer wie bei
``ki-dev run`` (:func:`~ki_dev.runner.graph.compile_flow`): ein Knoten
je Zustand von ``planning.toml``. Maschinenzustände (``checks``) führt
der Ausführer selbst aus; bei ``turn`` (Übergabe an eine Sitzung) und
``ask`` (der Mensch entscheidet) hält er mit ``interrupt``. Der
Checkpoint je Bead hält Zustand und Tatsachen für Wächter (z. B. kein
PASS nach Teillauf); eine Antwort gilt nur dort, wo der Thread wartet.

Welche Kante gilt, entscheidet allein der Ablauf über den gebundenen
Interpreter; was eine Maschinenoperation tut, reicht der Aufrufer als
benannte Implementierung herein (der Ausführer kennt step nicht). Der
Halt nennt Zustand, Operation und den in diesem Aufruf genommenen Weg;
daraus wählt der Adapter die Vorlage (Vorlage am Übergang).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command, interrupt

from ki_dev.flow.model import Flow, FlowError, State, Transition
from ki_dev.runner.graph import END_ROUTE, compile_flow
from ki_dev.runner.interpreter import Binding, BoundFlow, bind

TURN = "turn"
ASK = "ask"
CHECKS = "checks"
FULL_CHECKS = "full_checks"
CHECKPOINT_FILE = "checkpoints.sqlite"


@dataclass(frozen=True)
class PlanningContext:
    """Laufdaten für die Wächter: benannte Tatsachen (``full_checks``)
    und, nach einem Vorlauf, sein Ergebnis für die Übergabe."""

    facts: frozenset[str] = frozenset({FULL_CHECKS})
    outcome: object = None


@dataclass(frozen=True)
class Halt:
    """Wo der Lauf hält und auf welchem Weg er in diesem Aufruf kam."""

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


class PlanningGraphState(TypedDict):
    state: str
    facts: list[str]
    final: bool


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


def with_facts(
    context: PlanningContext, facts: frozenset[str], outcome: object
) -> PlanningContext:
    return replace(context, facts=facts, outcome=outcome)


@contextmanager
def planning_runtime(
    flow: Flow,
    directory: Path,
    thread: str,
    machine: Mapping[str, MachineOperation] | None = None,
) -> Iterator[PlanningRuntime]:
    """Ausführer mit Checkpoint ``directory/checkpoints.sqlite``; die
    Verbindung wird auch bei Fehlern geschlossen."""
    directory.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        directory / CHECKPOINT_FILE, check_same_thread=False
    )
    try:
        yield PlanningRuntime(
            flow, thread, dict(machine or {}), SqliteSaver(connection)
        )
    finally:
        connection.close()


class PlanningRuntime:
    """Ein Thread je Bead über dem gemeinsamen Graph-Übersetzer."""

    def __init__(
        self,
        flow: Flow,
        thread: str,
        machine: Mapping[str, MachineOperation],
        checkpointer: SqliteSaver,
    ) -> None:
        self.flow = flow
        self.bound = bind_planning(flow)
        self._machine = machine
        self._config = {"configurable": {"thread_id": thread}}
        self._graph = compile_flow(
            flow, PlanningGraphState, self._node, _route, checkpointer
        )
        self._path: list[Transition] = []
        self._outcome: object = None

    # --- Aufrufe ---

    def waiting(self) -> tuple[str, frozenset[str]] | None:
        """Gespeicherter Halt (Zustand, Tatsachen) oder ``None``."""
        values = self._graph.get_state(self._config).values
        if not values:
            return None
        return values["state"], frozenset(values["facts"])

    def start(self, state: str, event: str | None) -> Halt:
        """Ausdrücklicher Beginn in ``state`` (step --step); mit
        ``event`` gleich die erste Antwort dort."""
        self.flow.state(state)
        self._path, self._outcome = [], None
        self._graph.invoke(
            {"state": state, "facts": [FULL_CHECKS], "final": False},
            self._config,
        )
        if event is None:
            return self._halt()
        return self._answer(event)

    def resume(self, event: str) -> Halt:
        """Antwort an den wartenden Zustand; anderswo nicht erlaubt."""
        self._path, self._outcome = [], None
        return self._answer(event)

    def _answer(self, event: str) -> Halt:
        """Antwort erst gegen den Ablauf prüfen, dann fortsetzen: eine
        abgewiesene Antwort darf den Checkpoint nicht berühren (ein
        einmal übergebener Resume-Wert bliebe sonst hängen)."""
        snapshot = self._graph.get_state(self._config)
        if not snapshot.interrupts:
            raise FlowError("der Lauf wartet auf keine Antwort")
        state = snapshot.values["state"]
        context = PlanningContext(frozenset(snapshot.values["facts"]))
        if self.bound.select(state, event, context) is None:
            raise FlowError(
                f"Ereignis {event} in {state} nicht erlaubt"
            )
        self._graph.invoke(
            Command(resume={"event": event}), self._config
        )
        return self._halt()

    # --- Knoten ---

    def _node(self, flow_state: State) -> Callable:
        def run(values: PlanningGraphState) -> dict[str, object]:
            context = PlanningContext(frozenset(values["facts"]))
            operation = self.bound.operation(flow_state.id, context)
            if operation is None:
                return {"final": True}
            if operation.do in self._machine:
                event, context = self._machine[operation.do](
                    flow_state.id, context
                )
                self._outcome = context.outcome
                return self._take(flow_state.id, event, context)
            answer = interrupt(
                {"state": flow_state.id, "operation": operation.do}
            )
            return self._take(flow_state.id, answer["event"], context)

        return run

    def _take(
        self, state: str, event: str, context: PlanningContext
    ) -> dict[str, object]:
        transition = self.bound.select(state, event, context)
        if transition is None:
            raise FlowError(
                f"Ereignis {event} in {state} nicht erlaubt"
            )
        self._path.append(transition)
        return {
            "state": transition.target,
            "facts": sorted(context.facts),
        }

    # --- Halt ---

    def _halt(self) -> Halt:
        snapshot = self._graph.get_state(self._config)
        values = snapshot.values
        operation = None
        for item in snapshot.interrupts:
            operation = item.value["operation"]
        context = PlanningContext(
            frozenset(values["facts"]), self._outcome
        )
        return Halt(
            values["state"], operation, tuple(self._path), context
        )


def _route(values: PlanningGraphState) -> str:
    return END_ROUTE if values.get("final") else values["state"]
