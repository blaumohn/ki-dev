"""Ausführer des Planungsablaufs: ein Lauf je Bead.

``ki-dev step`` ist eine Projektion dieses Ausführers mit dem Adapter
``manual``. Kanten wählt python-statemachine aus dem ``[statechart]``,
das die Mustererweiterung aus ``planning.toml`` erzeugt
(:mod:`ki_dev.flow.statechart`); die Wächter sind Methoden von
:class:`PlanningModel`. Maschinenzustände (``checks``) führt der
Ausführer selbst aus; bei ``turn`` (Übergabe an eine Sitzung) und
``ask`` (der Mensch entscheidet) hält er, der Prozess endet. Der
Datensatz je Bead (``record.json``, atomar ersetzt) hält Zustand und
Tatsachen für Wächter (z. B. kein PASS nach Teillauf) sowie den Stand,
den die Maschinenoperation geprüft hat; eine Antwort gilt nur dort, wo
der Lauf wartet, und bringt den aktuellen Stand mit (Wächter
``unchanged``, synchron verglichen).

Was eine Maschinenoperation tut, reicht der Aufrufer als benannte
Implementierung herein (der Ausführer kennt step nicht). Der Halt nennt
Zustand, Operation und den in diesem Aufruf genommenen Weg; daraus
wählt der Halt die Übergabe (``Halt.turn``: Vorlage am Übergang oder an
der Operation des Zustands).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path

from jsonschema import Draft202012Validator

from ki_dev.flow.model import Flow, FlowError, Transition, Turn
from ki_dev.fsm import (
    RECORD_SCHEMA,
    Chart,
    Durable,
    TransitionNotAllowed,
    bind,
)
from ki_dev.run_store import RunStore, RunStoreError, replace_json

TURN = "turn"
ASK = "ask"
CHECKS = "checks"
FULL_CHECKS = "full_checks"
UNCHANGED = "unchanged"
RECORD_FILE = "record.json"


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


class PlanningModel:
    """Ops des Planungsablaufs: Wächter über den Laufdaten."""

    def __init__(self, context: PlanningContext) -> None:
        self.context = context

    def full_checks(self) -> bool:
        """Der Vorlauf lief vollständig (Tatsache der Operation)."""
        return FULL_CHECKS in self.context.facts

    def unchanged(self) -> bool:
        return _unchanged(self.context)


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


_CHARTS: dict[str, Chart] = {}


def _chart(flow: Flow) -> Chart:
    """Gebundene Definition je Ablaufstand (Namen gegen
    :class:`PlanningModel` geprüft)."""
    digest = flow_digest(flow)
    if digest not in _CHARTS:
        _CHARTS[digest] = bind(flow.statechart, PlanningModel)
    return _CHARTS[digest]


def allows(
    flow: Flow, state: str, event: str, context: PlanningContext
) -> bool:
    """Ob der Ablauf ``event`` in ``state`` mit diesen Laufdaten
    annimmt (Wächter), ohne einen Lauf zu verändern."""
    machine = Durable(
        _chart(flow),
        PlanningModel(context),
        {"state": [state], "history": {}},
    )
    try:
        machine.send(event)
    except TransitionNotAllowed:
        return False
    return True


def _holds(context: PlanningContext) -> Callable[[str], bool]:
    model = PlanningModel(context)
    return lambda name: getattr(model, name)()


_TEXTS = {"type": "object", "additionalProperties": {"type": "string"}}
_NAME_OR_NULL = {"anyOf": [{"type": "null"}, {"type": "string"}]}
_SCHEMA = {
    "type": "object",
    "required": [
        "flow_digest",
        "attempt",
        "run",
        "facts",
        "checked",
        "answer_file",
        "waiting",
    ],
    "additionalProperties": False,
    "properties": {
        "flow_digest": {"type": "string"},
        "attempt": {"type": "integer", "minimum": 1},
        "run": RECORD_SCHEMA,
        "facts": {"type": "array", "items": {"type": "string"}},
        "checked": {"anyOf": [{"type": "null"}, _TEXTS]},
        "answer_file": _NAME_OR_NULL,
        "waiting": _NAME_OR_NULL,
    },
}
_VALIDATOR = Draft202012Validator(_SCHEMA)


def read_waiting(
    flow: Flow, directory: Path
) -> tuple[str, frozenset[str]] | None:
    """Gespeicherter Halt (Zustand, Tatsachen) oder ``None``, rein
    lesend; ein Halt aus einem anderen Ablaufstand ist ein Fehler."""
    record = _checked(_read(directory / RECORD_FILE), flow_digest(flow))
    if record is None:
        return None
    return record["run"]["state"][-1], frozenset(record["facts"])


def _read(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StaleHaltError(
            "gespeicherter Halt ist unlesbar; mit --step neu beginnen"
        ) from exc


def _checked(record: dict | None, digest: str) -> dict | None:
    """Ein Halt aus einem anderen Ablaufstand oder in einem anderen
    Format ist veraltet: verständlicher Fehler statt KeyError."""
    if record is None:
        return None
    if (
        not _VALIDATOR.is_valid(record)
        or record["flow_digest"] != digest
    ):
        raise StaleHaltError(
            "gespeicherter Halt stammt aus einem anderen "
            "Ablaufstand; mit --step neu beginnen"
        )
    return record


@contextmanager
def planning_runtime(
    flow: Flow,
    directory: Path,
    thread: str,
    machine: Mapping[str, MachineOperation] | None = None,
) -> Iterator[PlanningRuntime]:
    """Ausführer mit Datensatz ``directory/record.json`` als einziger
    Schreiber dieses Beads; die Sperre fällt auch bei Fehlern."""
    directory.mkdir(parents=True, exist_ok=True)
    try:
        store = RunStore(directory.parent, directory.name)
        writer = store.acquire_writer()
    except RunStoreError as exc:
        raise FlowError(str(exc)) from exc
    try:
        yield PlanningRuntime(
            flow, directory, thread, dict(machine or {})
        )
    finally:
        writer.close()


class PlanningRuntime:
    """Ein Lauf je Bead über dem erzeugten ``[statechart]``."""

    def __init__(
        self,
        flow: Flow,
        directory: Path,
        thread: str,
        machine: Mapping[str, MachineOperation],
    ) -> None:
        self.flow = flow
        self._chart = _chart(flow)
        self._machine = machine
        self._digest = flow_digest(flow)
        self._file = directory / RECORD_FILE
        self._directory = directory
        self._thread = thread
        self._record: dict = {}
        self._path: list[Transition] = []
        self._outcome: object = None

    # --- Aufrufe ---

    def waiting(self) -> tuple[str, frozenset[str]] | None:
        """Gespeicherter Halt (Zustand, Tatsachen) oder ``None``; ein
        Halt aus einem anderen Ablaufstand ist ein Fehler."""
        return read_waiting(self.flow, self._directory)

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
        self._record = {
            "flow_digest": self._digest,
            "attempt": self._saved_attempt() + 1,
            "run": {"state": [state], "history": {}},
            "facts": [],
            "checked": None,
            "answer_file": None,
            "waiting": None,
        }
        self._drive()
        self._save()
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
        wurde; fehlt sie oder ist sie fremd, bleibt der Datensatz
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
        abgewiesene Antwort berührt den Datensatz nicht (gespeichert
        wird erst danach). Eine Antwort von außen beendet den Versuch,
        ein neuer beginnt."""
        record = _checked(_read(self._file), self._digest)
        if record is None or record["waiting"] is None:
            raise FlowError("der Lauf wartet auf keine Antwort")
        self._record = record
        if outside and check:
            self._check_attempt(record["attempt"], attempt)
        context = replace(
            self._context(),
            current=current,
            answer_file=answer_file or record["answer_file"],
        )
        self._take(self._state(), event, context)
        if outside:
            self._record["attempt"] += 1
        self._drive()
        self._save()
        return self._halt()

    def _check_attempt(self, number: int, attempt: str | None) -> None:
        waiting = self._attempt_id(number)
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
        try:
            saved = _read(self._file)
        except StaleHaltError:
            return 0
        if not isinstance(saved, dict):
            return 0
        attempt = saved.get("attempt", 0)
        return attempt if isinstance(attempt, int) else 0

    # --- Schritte ---

    def _drive(self) -> None:
        """Maschinenoperationen fahren, bis eine Antwort von außen
        nötig ist (``turn``, ``ask``) oder der Ablauf endet."""
        while True:
            state = self._state()
            context = self._context()
            operation = self.flow.operation(state, _holds(context))
            if operation is None or operation.do not in self._machine:
                self._record["waiting"] = (
                    None if operation is None else operation.do
                )
                return
            event, context = self._machine[operation.do](
                state, context
            )
            self._outcome = context.outcome
            self._take(state, event, context)

    def _take(
        self, state: str, event: str, context: PlanningContext
    ) -> None:
        machine = Durable(
            self._chart, PlanningModel(context), self._record["run"]
        )
        try:
            taken = machine.send(event)
        except TransitionNotAllowed:
            raise FlowError(
                f"Ereignis {event} in {state} nicht erlaubt"
            ) from None
        self._path.append(
            self.flow.edge(taken.owner, taken.index, state)
        )
        self._record.update(
            run=machine.record,
            facts=sorted(context.facts),
            checked=_plain(context.checked),
            answer_file=context.answer_file,
        )

    def _save(self) -> None:
        replace_json(self._file, self._record)

    def _state(self) -> str:
        return self._record["run"]["state"][-1]

    def _context(self) -> PlanningContext:
        return PlanningContext(
            frozenset(self._record["facts"]),
            checked=self._record["checked"],
            answer_file=self._record["answer_file"],
        )

    # --- Halt ---

    def _halt(self) -> Halt:
        context = replace(self._context(), outcome=self._outcome)
        waiting = self._record["waiting"]
        state = self._state()
        return Halt(
            state,
            waiting,
            tuple(self._path),
            context,
            self._turn(state, context),
            (
                self._attempt_id(self._record["attempt"])
                if waiting
                else None
            ),
        )

    def _turn(
        self, state: str, context: PlanningContext
    ) -> Turn | None:
        for transition in reversed(self._path):
            if transition.turn is not None:
                return transition.turn
        operation = self.flow.operation(state, _holds(context))
        return None if operation is None else operation.turn


def _plain(stand: Mapping[str, str] | None) -> dict[str, str] | None:
    """Stand als einfaches dict für den Datensatz (serialisierbar)."""
    return None if stand is None else dict(stand)
