"""Ausführer des Planungsablaufs: LangGraph-Thread je Bead.

``ki-dev step`` ist eine Projektion dieses Ausführers mit dem Adapter
``manual``. Der Graph entsteht mit demselben Übersetzer wie bei
``ki-dev -f implement`` (:func:`~ki_dev.runner.graph.compile_flow`):
ein Knoten je Zustand von ``planning.toml``. Maschinenzustände
(``checks``) führt der Ausführer selbst aus; bei ``turn`` (Übergabe
an eine Sitzung) und ``ask`` (der Mensch entscheidet) hält er mit
``interrupt``. Der
Checkpoint je Bead hält Zustand und Tatsachen für Wächter (z. B. kein
PASS nach Teillauf) sowie den Stand, den die Maschinenoperation geprüft
hat; eine Antwort gilt nur dort, wo der Thread wartet, und bringt den
aktuellen Stand mit (Wächter ``unchanged``, synchron verglichen).

Welche Kante gilt, entscheidet allein der Ablauf über den gebundenen
Interpreter; was eine Maschinenoperation tut, reicht der Aufrufer als
benannte Implementierung herein (der Ausführer kennt step nicht). Der
Halt nennt Zustand, Operation und den in diesem Aufruf genommenen Weg;
daraus wählt der Halt die Übergabe (``Halt.turn``: Vorlage am
Übergang oder an der Operation des Zustands).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command, interrupt

from ki_dev.flow.model import Flow, FlowError, State, Transition, Turn
from ki_dev.runner.graph import END_ROUTE, compile_flow
from ki_dev.runner.interpreter import Binding, BoundFlow, bind

TURN = "turn"
ASK = "ask"
CHECKS = "checks"
FULL_CHECKS = "full_checks"
UNCHANGED = "unchanged"
CHECKPOINT_FILE = "checkpoints.sqlite"


@dataclass(frozen=True)
class PlanningContext:
    """Laufdaten für die Wächter: benannte Tatsachen (``full_checks``)
    und, nach einem Vorlauf, sein Ergebnis für die Übergabe. Tatsachen
    beginnen leer: nur die Operation, die sie belegt, setzt sie."""

    facts: frozenset[str] = frozenset()
    outcome: object = None
    checked: Mapping[str, str] | None = None
    """Stand, auf dem die Maschinenoperation geprüft hat."""
    current: Mapping[str, str] | None = None
    """Stand beim Eingang der Antwort (vom Aufrufer ermittelt)."""
    answer_file: str | None = None
    """Antwortdatei, die bei einem späteren Vorlauf auszunehmen ist."""


@dataclass(frozen=True)
class Halt:
    """Wo der Lauf hält und auf welchem Weg er in diesem Aufruf kam."""

    state: str
    operation: str | None
    path: tuple[Transition, ...] = ()
    context: PlanningContext = field(default_factory=PlanningContext)
    turn: Turn | None = None
    """Die Übergabe dieses Halts laut Ablauf: die der letzten Kante
    des Weges, die eine bestimmt, sonst die Operation des Zustands."""
    attempt: str | None = None
    """Kennung des wartenden Versuchs (``None``, wenn nichts wartet):
    eine Antwort gilt nur für den Versuch, für den die Übergabe
    ausgegeben wurde."""

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
    attempt: int
    facts: list[str]
    checked: dict[str, str] | None
    answer_file: str | None
    flow_digest: str
    final: bool


class StaleHaltError(FlowError):
    """Der gespeicherte Halt stammt aus einem anderen Ablaufstand."""


class StaleAnswerError(FlowError):
    """Die Antwort gehört nicht zum wartenden Versuch."""


def flow_digest(flow: Flow) -> str:
    """Fingerabdruck der Topologie (Zustände, Kanten mit Wächtern):
    ändert sich er, passt ein gespeicherter Halt nicht mehr. Texte wie
    Hinweise gehören nicht dazu."""
    shape = {
        "states": sorted(
            (state.id, state.kind) for state in flow.states.values()
        ),
        "transitions": [
            (t.source, t.event, list(t.cond), t.target)
            for t in flow.transitions
        ],
    }
    text = json.dumps(shape, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def bind_planning(flow: Flow) -> BoundFlow[PlanningContext]:
    return bind(
        flow,
        Binding(
            guards={
                FULL_CHECKS: lambda context: (
                    FULL_CHECKS in context.facts
                ),
                UNCHANGED: _unchanged,
            },
            actions={},
            escalations=frozenset(),
            operations=frozenset({TURN, ASK, CHECKS}),
        ),
    )


def _unchanged(context: PlanningContext) -> bool:
    """Geprüfter und aktueller Stand sind bekannt und gleich; ohne
    geprüften Stand gibt es nichts, das unverändert sein könnte."""
    return (
        context.checked is not None
        and context.current is not None
        and dict(context.checked) == dict(context.current)
    )


def with_facts(
    context: PlanningContext,
    facts: frozenset[str],
    outcome: object,
    checked: Mapping[str, str] | None = None,
) -> PlanningContext:
    return replace(
        context, facts=facts, outcome=outcome, checked=checked
    )


def _context(
    values: PlanningGraphState,
    current: Mapping[str, str] | None = None,
) -> PlanningContext:
    return PlanningContext(
        frozenset(values["facts"]),
        checked=values.get("checked"),
        current=current,
        answer_file=values.get("answer_file"),
    )


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
        self._digest = flow_digest(flow)
        self._checkpointer = checkpointer
        self._thread = thread
        self._config = {"configurable": {"thread_id": thread}}
        self._graph = compile_flow(
            flow, PlanningGraphState, self._node, _route, checkpointer
        )
        self._path: list[Transition] = []
        self._outcome: object = None

    # --- Aufrufe ---

    def waiting(self) -> tuple[str, frozenset[str]] | None:
        """Gespeicherter Halt (Zustand, Tatsachen) oder ``None``; ein
        Halt aus einem anderen Ablaufstand ist ein Fehler."""
        if self._saved_digest() is None:
            return None
        values = self._graph.get_state(self._config).values
        return values["state"], frozenset(values["facts"])

    def _saved_digest(self) -> str | None:
        """Fingerabdruck des gespeicherten Halts, geprüft, bevor der
        Graph ihn liest (ein umbenannter Zustand wäre sonst ein
        KeyError tief in LangGraph). Ein Halt aus der Zeit vor der
        Versuchskennung gilt ebenso als veraltet."""
        saved = self._checkpointer.get_tuple(self._config)
        if saved is None:
            return None
        values = saved.checkpoint.get("channel_values", {})
        digest = values.get("flow_digest")
        if digest != self._digest or "attempt" not in values:
            raise StaleHaltError(
                "gespeicherter Halt stammt aus einem anderen "
                "Ablaufstand; mit --step neu beginnen"
            )
        return digest

    def start(
        self,
        state: str,
        event: str | None,
        current: Mapping[str, str] | None = None,
    ) -> Halt:
        """Ausdrücklicher Beginn in ``state`` (step --step); mit
        ``event`` gleich die erste Antwort dort."""
        self.flow.state(state)
        self._path, self._outcome = [], None
        self._graph.invoke(
            {
                "state": state,
                "attempt": self._saved_attempt() + 1,
                "facts": [],
                "checked": None,
                "answer_file": None,
                "flow_digest": self._digest,
                "final": False,
            },
            self._config,
        )
        if event is None:
            return self._halt()
        return self._answer(event, current, None)

    def resume(
        self,
        event: str,
        current: Mapping[str, str] | None = None,
        attempt: str | None = None,
        answer_file: str | None = None,
    ) -> Halt:
        """Antwort an den wartenden Zustand; anderswo nicht erlaubt.
        ``current`` ist der Stand beim Eingang der Antwort, ``attempt``
        die Kennung des Versuchs, für den die Übergabe ausgegeben
        wurde; fehlt sie oder ist sie fremd, bleibt der Checkpoint
        unverändert."""
        self._path, self._outcome = [], None
        return self._answer(
            event,
            current,
            attempt,
            outside=True,
            answer_file=answer_file,
        )

    def advance(
        self, event: str, current: Mapping[str, str] | None = None
    ) -> Halt:
        """Der Mensch geht weiter (Schreiben oder Korrektur ist getan):
        ein Befehl, keine Antwort einer Sitzung, also ohne Kennung. Er
        beendet den Versuch wie eine Antwort."""
        self._path, self._outcome = [], None
        return self._answer(
            event, current, None, outside=True, check=False
        )

    def _answer(
        self,
        event: str,
        current: Mapping[str, str] | None,
        attempt: str | None,
        *,
        outside: bool = False,
        check: bool = True,
        answer_file: str | None = None,
    ) -> Halt:
        """Antwort erst gegen den Ablauf prüfen, dann fortsetzen: eine
        abgewiesene Antwort darf den Checkpoint nicht berühren (ein
        einmal übergebener Resume-Wert bliebe sonst hängen). Eine
        Antwort von außen beendet den Versuch, ein neuer beginnt."""
        self._saved_digest()
        snapshot = self._graph.get_state(self._config)
        if not snapshot.interrupts:
            raise FlowError("der Lauf wartet auf keine Antwort")
        if outside and check:
            self._check_attempt(snapshot.values, attempt)
        state = snapshot.values["state"]
        context = _context(snapshot.values, current)
        if self.bound.select(state, event, context) is None:
            raise FlowError(
                f"Ereignis {event} in {state} nicht erlaubt"
            )
        resume = {
            "event": event,
            "current": _plain(current),
            "next_attempt": outside,
            "answer_file": answer_file,
        }
        self._graph.invoke(Command(resume=resume), self._config)
        return self._halt()

    def _check_attempt(
        self, values: PlanningGraphState, attempt: str | None
    ) -> None:
        waiting = self._attempt_id(values["attempt"])
        if attempt is None:
            raise StaleAnswerError(
                f"attempt fehlt (wartend: Versuch {waiting})"
            )
        if attempt != waiting:
            raise StaleAnswerError(
                "attempt gehört nicht zum wartenden Versuch "
                f"(wartend: Versuch {waiting})"
            )

    def _attempt_id(self, number: int) -> str:
        return f"{self._thread}:{number}"

    def _saved_attempt(self) -> int:
        """Zähler des gespeicherten Laufs (auch eines anderen
        Ablaufstands): ein neuer Beginn nutzt nie eine alte Kennung."""
        saved = self._checkpointer.get_tuple(self._config)
        if saved is None:
            return 0
        values = saved.checkpoint.get("channel_values", {})
        return int(values.get("attempt", 0))

    # --- Knoten ---

    def _node(self, flow_state: State) -> Callable:
        def run(values: PlanningGraphState) -> dict[str, object]:
            context = _context(values)
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
            context = replace(
                context,
                current=answer.get("current"),
                answer_file=(
                    answer.get("answer_file") or context.answer_file
                ),
            )
            update = self._take(flow_state.id, answer["event"], context)
            if answer.get("next_attempt"):
                update["attempt"] = values["attempt"] + 1
            return update

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
            "checked": _plain(context.checked),
            "answer_file": context.answer_file,
        }

    # --- Halt ---

    def _halt(self) -> Halt:
        snapshot = self._graph.get_state(self._config)
        values = snapshot.values
        operation = None
        for item in snapshot.interrupts:
            operation = item.value["operation"]
        context = replace(_context(values), outcome=self._outcome)
        waiting = bool(snapshot.interrupts)
        return Halt(
            values["state"],
            operation,
            tuple(self._path),
            context,
            self._turn(values["state"], context),
            self._attempt_id(values["attempt"]) if waiting else None,
        )

    def _turn(
        self, state: str, context: PlanningContext
    ) -> Turn | None:
        for transition in reversed(self._path):
            if transition.turn is not None:
                return transition.turn
        operation = self.bound.operation(state, context)
        return None if operation is None else operation.turn


def _plain(stand: Mapping[str, str] | None) -> dict[str, str] | None:
    """Stand als einfaches dict für den Checkpoint (serialisierbar)."""
    return None if stand is None else dict(stand)


def _route(values: PlanningGraphState) -> str:
    return END_ROUTE if values.get("final") else values["state"]
