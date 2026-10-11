"""Lauf-Maschine des Ausführers: eine parallele Statechart.

Die Regionen ``operation`` und ``halt`` stehen in ``runner/run.toml``
(natives Format von python-statemachine); die Region ``ablauf`` ist der
``[statechart]`` des Ablaufs, den :func:`compose` beim Laden einsetzt.
Ein Modell trägt beide Seiten (:class:`RunModel` und die Ops des
Ablaufs), ``fsm.bind`` prüft die Namen beider.

:class:`RunMachine` ist die Sicht des Ausführers: Lauf-Ereignisse
senden, Ablauf-Ereignisse fortschreiben (:meth:`RunMachine.advance`),
Status lesen, Datensatz bilden. Die Kopplung trägt die Bibliothek: eine
Eskalation des Ablaufs hält ``halt`` an, ein wartender Ablaufzustand
ebenso, das Ende des Ablaufs beendet den Lauf. Der Ausführer leitet aus
Phasen keine Lauf-Ereignisse ab.
"""

from __future__ import annotations

import copy
import tomllib
from collections.abc import Iterator, Mapping
from importlib.resources import files

from ki_dev.fsm import Durable, bind, check_record, configuration_of
from ki_dev.runner.machine import (
    DEFAULT_LIMITS,
    IMPLEMENT,
    OPERATION_GUARDS,
    Event,
    ImplementModel,
    Limits,
    MachineState,
    Phase,
    TransitionResult,
    phase_of,
    step,
)

Operation = dict[str, object]
"""Offene Operation: ``id``, ``kind``, ``repeatable``, ``call_id``."""

ABLAUF = "ablauf"
"""Name der Region, in die :func:`compose` den Ablauf einsetzt."""

_ROOT = "lauf"
_HALT = "halt"


class RunModel:
    """Ops der Regionen ``operation`` und ``halt``: die offene
    Operation."""

    def __init__(self, pending: Operation | None = None) -> None:
        self.pending = pending

    def is_running(self, machine: object) -> bool:
        """Region halt fährt (kein Halt)."""
        return machine.running.is_active  # type: ignore[attr-defined]

    def repeatable(self) -> bool:
        """Die offene Operation darf nach Prozessende erneut laufen."""
        return self.pending is not None and bool(
            self.pending["repeatable"]
        )

    def hold_operation(self, operation: Operation) -> None:
        self.pending = {**operation, "call_id": None}

    def begin_operation(self, call_id: str | None = None) -> None:
        """Absicht: die Wirkung beginnt (mit Budgetbuchung)."""
        self.pending = {**self.pending, "call_id": call_id}

    def drop_operation(self) -> None:
        self.pending = None


class LaufModel(RunModel, ImplementModel):
    """Ein Modell für alle Regionen: offene Operation und Stand des
    Ablaufs (Zähler, Ergebnisflag, Eskalation)."""

    def __init__(
        self, pending: Operation | None, state: MachineState
    ) -> None:
        RunModel.__init__(self, pending)
        ImplementModel.__init__(self, state)

    def _load_flow(
        self,
        state: MachineState,
        limits: Limits,
        facts: frozenset[str],
    ) -> None:
        """Stand des Ablaufs vor einem Ablauf-Ereignis."""
        ImplementModel.__init__(self, state, limits, facts)


def compose(run: Mapping, flow: Mapping) -> dict:
    """Lauf mit dem Ablauf als Region :data:`ABLAUF`."""
    doc = copy.deepcopy(dict(run))
    root = doc["states"][_ROOT]
    root["states"] = {
        ABLAUF: {"states": copy.deepcopy(flow["states"])},
        **root["states"],
    }
    return doc


def _load_doc() -> dict:
    text = files("ki_dev.runner").joinpath("run.toml").read_text(
        encoding="utf-8"
    )
    return tomllib.loads(text)["statechart"]


def _ids(states: Mapping) -> Iterator[str]:
    for sid, state in states.items():
        yield sid
        yield from _ids(state.get("states", {}))


_RUN_DOC = _load_doc()
LAUF_CHART = bind(
    compose(_RUN_DOC, IMPLEMENT.statechart),
    LaufModel,
    also=OPERATION_GUARDS,
)
_FLOW_IDS = frozenset({ABLAUF, *_ids(IMPLEMENT.statechart["states"])})
_HALT_STATES = _RUN_DOC["states"][_ROOT]["states"][_HALT]["states"]
_RUNNING = next(
    sid for sid, state in _HALT_STATES.items() if state.get("initial")
)
_BY_FLOW = frozenset({"waiting", "finished"})
"""Halte, die der Ablauf auslöst: welcher es ist, sagt sein Zustand."""


def _walk(states: Mapping) -> Iterator[Mapping]:
    for state in states.values():
        yield state
        yield from _walk(state.get("states", {}))


_RUN_EVENTS = frozenset(
    transition["event"]
    for state in _walk(_RUN_DOC["states"])
    for transition in state.get("transitions", ())
    if not transition["event"].startswith("done.")
) - {"escalation", "wait"}
"""Ereignisse, die der Ausführer dem Lauf sendet (ohne die, die der
Ablauf oder die Bibliothek auslöst)."""


class RunMachine:
    """Lauf eines Ablaufs, wiederhergestellt aus Datensatz, offener
    Operation und Ablaufzustand (``state``, aus den Laufdaten)."""

    def __init__(
        self,
        record: Mapping[str, object] | None = None,
        pending: Operation | None = None,
        state: MachineState | None = None,
    ) -> None:
        flow = state or MachineState(phase=Phase.START)
        self._model = LaufModel(pending, flow)
        full = None
        if record is not None:
            check_record(record)
            chain = configuration_of(LAUF_CHART, flow.phase.value)
            stored = list(record["state"])  # type: ignore[arg-type]
            full = {
                "state": stored + [s for s in chain if s not in stored],
                "history": record["history"],
            }
        self._machine = Durable(LAUF_CHART, self._model, full)

    def send(self, event: str, **kwargs: object) -> None:
        """Ereignis des Laufs (Operation, Halt, Fortsetzen)."""
        self._machine.send(event, **kwargs)

    def advance(
        self,
        state: MachineState,
        event: Event,
        limits: Limits = DEFAULT_LIMITS,
        *,
        facts: frozenset[str] = frozenset(),
    ) -> TransitionResult:
        """Ereignis des Ablaufs über dieselbe Maschine: was es im Lauf
        auslöst (Halt, Ende), nimmt die Bibliothek mit."""
        if self.phase is not state.phase:
            raise RuntimeError(
                f"Ablauf steht in {self.phase.value}, Laufdaten in "
                f"{state.phase.value}"
            )
        self._model._load_flow(state, limits, facts)
        return step(self._machine, self._model, state, event)

    @property
    def phase(self) -> Phase:
        return phase_of(self._machine.configuration)

    @property
    def status(self) -> str:
        """Status des Laufs: der Halt; löst ihn der Ablauf aus
        (wartend, beendet), nennt ihn dessen Zustand."""
        (halt,) = (
            sid for sid in self._machine.configuration
            if sid in _HALT_STATES
        )
        return self.phase.value if halt in _BY_FLOW else halt

    @property
    def halted(self) -> bool:
        """Der Aufruf endet: der Lauf fährt nicht."""
        return _RUNNING not in self._machine.configuration

    @property
    def allowed(self) -> list[str]:
        """Ereignisse des Laufs, die jetzt eine Kante haben (Wächter
        ausgewertet)."""
        events = self._machine.machine.enabled_events()
        return sorted(
            {str(event) for event in events} & _RUN_EVENTS
        )

    @property
    def started(self) -> bool:
        """Absicht gespeichert, Ergebnis noch nicht."""
        return self._machine.machine.started.is_active

    @property
    def pending(self) -> Operation | None:
        return self._model.pending

    @property
    def record(self) -> dict[str, object]:
        """Datensatz der Regionen ``operation`` und ``halt``; den
        Ablaufzustand tragen die Laufdaten (eine Quelle)."""
        record = self._machine.record
        return {
            **record,
            "state": [
                sid for sid in record["state"]  # type: ignore[union-attr]
                if sid not in _FLOW_IDS
            ],
        }
