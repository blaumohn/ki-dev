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

Jede genommene Kante wird ein :class:`Step` ihrer Region
(:meth:`RunMachine.drain_steps`); der Ausführer schreibt sie ins
Ereignisprotokoll, bevor er den Datensatz ersetzt.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from ki_dev.flow.model import Transition
from ki_dev.fsm import (
    Durable,
    Taken,
    bind,
    check_record,
    configuration_of,
)
from ki_dev.runner.events import ABLAUF, MACHINE
from ki_dev.runner.machine import (
    IMPLEMENT,
    OPERATION_GUARDS,
    Event,
    ImplementModel,
    Limits,
    MachineState,
    Phase,
    RunState,
    TransitionResult,
    phase_of,
    step,
)
from ki_dev.runner.protocol import RUN_DOC, RunModel, compose

Operation = dict[str, object]
"""Offene Operation: ``id``, ``kind``, ``repeatable``, ``call_id``."""


_ROOT = "lauf"
_HALT = "halt"




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




def _ids(states: Mapping) -> Iterator[str]:
    for sid, state in states.items():
        yield sid
        yield from _ids(state.get("states", {}))


LAUF_CHART = bind(
    compose(RUN_DOC, IMPLEMENT.statechart),
    LaufModel,
    also=OPERATION_GUARDS,
)
_FLOW_IDS = frozenset({ABLAUF, *_ids(IMPLEMENT.statechart["states"])})
_HALT_STATES = RUN_DOC["states"][_ROOT]["states"][_HALT]["states"]
_RUNNING = next(
    sid for sid, state in _HALT_STATES.items() if state.get("initial")
)
_BY_FLOW = frozenset({"waiting", "finished"})
"""Halte, die der Ablauf auslöst: welcher es ist, sagt sein Zustand."""


def _walk(states: Mapping) -> Iterator[Mapping]:
    for state in states.values():
        yield state
        yield from _walk(state.get("states", {}))


def _owned(states: Mapping) -> Iterator[tuple[str, Mapping]]:
    for sid, state in states.items():
        yield sid, state
        yield from _owned(state.get("states", {}))


_REGION = {
    sid: region
    for region, state in RUN_DOC["states"][_ROOT]["states"].items()
    for sid in (region, *_ids(state.get("states", {})))
} | dict.fromkeys(_FLOW_IDS, ABLAUF)
"""Region je Zustand (Eigentümer einer Kante)."""
_RUN_ITEMS = {
    (sid, index): item
    for sid, state in _owned(RUN_DOC["states"])
    for index, item in enumerate(state.get("transitions", ()))
}


def _names(value: object) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [item for item in items if isinstance(item, str)]


def _run_transition(taken: Taken) -> Transition:
    """Kante einer Lauf-Region in der Form des Protokolls."""
    item = _RUN_ITEMS[(taken.owner, taken.index)]
    return Transition(
        source=taken.owner,
        event=taken.event,
        target=taken.target,
        cond=(
            *_names(item.get("cond")),
            *(f"!{name}" for name in _names(item.get("unless"))),
        ),
        actions=tuple(_names(item.get("on"))),
    )


@dataclass(frozen=True)
class Step:
    """Genommene Kante für das Ereignisprotokoll: ihre Region, die
    Revision des Ablaufs (nach einer Ablaufkante die neue), die Kante
    und wer das Ereignis geliefert hat."""

    region: str
    seq: int
    transition: Transition
    adapter: str


_RUN_EVENTS = frozenset(
    transition["event"]
    for state in _walk(RUN_DOC["states"])
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
        revision: int = 0,
    ) -> None:
        flow = state or MachineState(phase=Phase.START)
        self._revision = revision
        self._steps: list[Step] = []
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
        self._collect(self.phase, MACHINE)

    def advance(
        self,
        run: RunState,
        event: Event,
        *,
        facts: frozenset[str] = frozenset(),
        adapter: str = MACHINE,
    ) -> TransitionResult:
        """Ereignis des Ablaufs über dieselbe Maschine: was es im Lauf
        auslöst (Halt, Ende), nimmt die Bibliothek mit. ``adapter``
        hat das Ereignis geliefert (Protokoll)."""
        state = run.state
        if self.phase is not state.phase:
            raise RuntimeError(
                f"Ablauf steht in {self.phase.value}, Laufdaten in "
                f"{state.phase.value}"
            )
        self._model._load_flow(state, run.limits, facts)
        result = step(self._machine, self._model, state, event)
        self._revision = run.revision + 1
        self._collect(state.phase, adapter)
        return result

    def _collect(self, source: Phase, adapter: str) -> None:
        """Genommene Kanten als Schritte ihrer Region; im Ablauf nur
        Kanten der Sicht (nicht der Empfänger eines ``raise``),
        genommen im innersten Zustand ``source``."""
        for taken in self._machine.journal:
            region = _REGION[taken.owner]
            if region != ABLAUF:
                self._steps.append(
                    Step(
                        region,
                        self._revision,
                        _run_transition(taken),
                        MACHINE,
                    )
                )
                continue
            key = (taken.owner, taken.index, source.value)
            if key in IMPLEMENT.edges:
                self._steps.append(
                    Step(
                        region,
                        self._revision,
                        IMPLEMENT.edges[key],
                        adapter,
                    )
                )
        self._machine.journal.clear()

    def drain_steps(self) -> list[Step]:
        """Seit dem letzten Aufruf genommene Kanten, in Reihenfolge."""
        steps, self._steps = self._steps, []
        return steps

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
