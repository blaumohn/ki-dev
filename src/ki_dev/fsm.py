"""Gerüst für deklarierte Zustandsmaschinen auf python-statemachine.

Der FSM-Kern eines Ablaufs (``[statechart]``) und die Maschinen des
Gerüsts (Lauf, Operation) stehen im nativen Format der Bibliothek;
Kantenwahl, verschachtelte Zustände, History und ``raise`` übernimmt
sie. Dieses Modul schließt ihre stillen Fallen:

* Ein unbekannter Name in ``cond``/``on``/… gälte als falsch:
  :func:`bind` prüft beim Laden alle Namen gegen die Ops-Klasse, in
  beide Richtungen.
* Ein Ereignis ohne Kante würde ignoriert, ein Fehler in einem
  Callback zum Ereignis ``error.execution``: :func:`load_statechart`
  schaltet beides ab.
* Ein mit ``raise`` erzeugtes Ereignis ohne Empfänger verfiele still:
  :func:`bind` verlangt eine Kante im Ziel oder darüber.
* Ein Callback, der wie ein Ereignis heißt, sendet dieses Ereignis
  statt die Methode aufzurufen: :func:`bind` weist solche Namen ab.
* Ereignisse und Zustände werden Attribute der Maschinenklasse; ein
  Name wie ``prepare`` verdeckt eines der Bibliothek: :func:`bind`
  weist solche Namen ab.
* ``history_values`` liegen nicht im Modell und die Konfiguration ist
  ``str`` oder ``OrderedSet``: :class:`Durable` speichert und lädt
  beides als Datensatz (:data:`RECORD_SCHEMA`).

``cond`` und Aktionen sind nur Bezeichner, keine Ausdrücke; das
``datamodel`` der Bibliothek wird nicht benutzt. Callbacks sind rein:
externe Wirkung führt der Aufrufer außerhalb von :meth:`Durable.send`
aus.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import cast

from jsonschema import Draft202012Validator
from statemachine import StateChart
from statemachine.exceptions import InvalidDefinition
from statemachine.io import load
from statemachine.orderedset import OrderedSet

TransitionNotAllowed = StateChart.TransitionNotAllowed

_NAME_KEYS = ("cond", "unless", "on", "before", "after")
_STATE_NAME_KEYS = ("enter", "exit")


class FsmError(ValueError):
    """Definition passt nicht zu ihren Ops (Programmfehler)."""


class RecordError(ValueError):
    """Datensatz verletzt Schema oder Definition (Feldpfad)."""


@dataclass(frozen=True)
class Chart:
    """Geladene, an eine Ops-Klasse gebundene Definition."""

    machine: type[StateChart]
    ops: type
    doc: Mapping[str, object]


@dataclass(frozen=True)
class Taken:
    """Genommene Kante: deklariert in ``owner`` an Stelle ``index``
    seiner ``transitions``."""

    owner: str
    index: int


def load_statechart(doc: Mapping[str, object]) -> type[StateChart]:
    """Native Definition laden und gegen das Schema der Bibliothek
    prüfen; die Klasse läuft strikt."""
    shadowed = sorted(
        (_events(doc) | set(_ids(doc))) & set(dir(StateChart))
    )
    if shadowed:
        raise FsmError(
            f"{doc.get('name')}: Name verdeckt die Bibliothek: "
            f"{', '.join(shadowed)}"
        )
    try:
        machine = load(json.dumps(doc), format="json", validate=True)
    except InvalidDefinition as exc:
        raise FsmError(f"{doc.get('name')}: {exc}") from exc
    machine.allow_event_without_transition = False
    machine.catch_errors_as_events = False
    return machine


def bind(
    doc: Mapping[str, object],
    ops: type,
    *,
    also: frozenset[str] = frozenset(),
) -> Chart:
    """Definition laden und mit ``ops`` abgleichen: jeder Name ist ein
    öffentliches aufrufbares Attribut, jedes solche Attribut wird
    genutzt (``also``: Namen, die eine Fachschicht nutzt)."""
    machine = load_statechart(doc)
    used = _used_names(doc) | also
    where = str(doc.get("name"))
    _check_names(where, used, ops)
    clash = sorted(used & _events(doc))
    if clash:
        raise FsmError(
            f"{where}: Callback heißt wie ein Ereignis: "
            f"{', '.join(clash)}"
        )
    _check_raises(doc)
    return Chart(machine, ops, doc)


def configuration_of(chart: Chart, state: str) -> list[str]:
    """Aktive Konfiguration, wenn ``state`` der innerste Zustand ist:
    Vorfahren von außen nach innen, dann ``state``."""
    try:
        current = chart.machine.states_map[state]
    except KeyError:
        raise RecordError(
            f"state: unbekannter Zustand {state}"
        ) from None
    chain = []
    while current is not None:
        chain.append(current.id)
        current = current.parent
    return chain[::-1]


def history_ids(chart: Chart) -> tuple[str, ...]:
    """History-Pseudozustände der Definition."""
    return tuple(_history_ids(chart.doc["states"]))


class Durable:
    """Maschine, deren Konfiguration und History ein Datensatz trägt.

    ``model`` ist eine Instanz der Ops-Klasse; ihre Felder speichert
    der Aufrufer selbst. ``record`` stellt einen gespeicherten Stand
    wieder her, ohne Eintrittsaktionen erneut auszuführen."""

    def __init__(
        self,
        chart: Chart,
        model: object,
        record: Mapping[str, object] | None = None,
    ) -> None:
        if not isinstance(model, chart.ops):
            raise TypeError(
                f"Modell muss {chart.ops.__name__} sein, nicht "
                f"{type(model).__name__}"
            )
        self._taken: list[Taken] = []
        if record is not None:
            check_record(record)
            state = cast(list[str], record["state"])
            _check_known(chart, state, "state")
            model.state = (  # type: ignore[attr-defined]
                state[0] if len(state) == 1 else OrderedSet(state)
            )
        self.machine = chart.machine(model=model, listeners=[self])
        self._origin = {
            id(transition): Taken(state.id, index)
            for state in self.machine.states_map.values()
            for index, transition in enumerate(state.transitions)
        }
        if record is not None:
            self.machine.history_values = _history_values(
                chart, self.machine, record
            )
        self._taken.clear()

    def send(self, event: str, **kwargs: object) -> Taken:
        """Ereignis senden; die Kante des Ereignisses selbst (nicht die
        der dabei mit ``raise`` erzeugten). ``kwargs`` erhalten die
        Callbacks über ihre Parameternamen."""
        self._taken.clear()
        self.machine.send(event, **kwargs)
        return self._taken[0]

    def after_transition(self, transition: object) -> None:
        """Listener der Bibliothek: genommene Kanten mitschreiben."""
        self._taken.append(self._origin[id(transition)])

    @property
    def configuration(self) -> list[str]:
        return [state.id for state in self.machine.configuration]

    @property
    def record(self) -> dict[str, object]:
        """Datensatz: aktive Konfiguration und History."""
        return {
            "state": self.configuration,
            "history": {
                key: [state.id for state in states]
                for key, states in self.machine.history_values.items()
            },
        }


_ID = {"type": "string", "pattern": r"^[A-Za-z_][A-Za-z0-9_]*$"}
_IDS = {"type": "array", "uniqueItems": True, "items": _ID}

RECORD_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["state", "history"],
    "additionalProperties": False,
    "properties": {
        "state": {**_IDS, "minItems": 1},
        "history": {"type": "object", "additionalProperties": _IDS},
    },
}
_RECORD_VALIDATOR = Draft202012Validator(RECORD_SCHEMA)


def check_record(record: object) -> None:
    """Datensatz gegen :data:`RECORD_SCHEMA` prüfen (Feldpfad, ohne
    Rohwerte)."""
    errors = sorted(
        _RECORD_VALIDATOR.iter_errors(record),
        key=lambda e: list(map(str, e.absolute_path)),
    )
    if errors:
        error = errors[0]
        path = [str(part) for part in error.absolute_path]
        if error.validator == "required":
            path.append(
                next(k for k in error.validator_value
                     if k not in error.instance)
            )
        raise RecordError(
            f"{'.'.join(path) or '$'}: {error.validator}"
        )


# --- Namen und raise -------------------------------------------------


def _used_names(doc: Mapping[str, object]) -> set[str]:
    names: set[str] = set()
    for state in _walk(cast(Mapping, doc["states"])):
        for key in _STATE_NAME_KEYS:
            names |= _callbacks(state.get(key))
        for transition in state.get("transitions", ()):
            for key in _NAME_KEYS:
                names |= _callbacks(transition.get(key))
    return names


def _events(doc: Mapping[str, object]) -> set[str]:
    return {
        transition["event"]
        for state in _walk(cast(Mapping, doc["states"]))
        for transition in state.get("transitions", ())
        if transition.get("event")
    }


def _ids(doc: Mapping[str, object]) -> Iterator[str]:
    states = cast(Mapping, doc["states"])
    for sid, state in _items(states):
        yield sid
        yield from state.get("history", {})


def _callbacks(value: object) -> set[str]:
    """Bezeichner einer Callback-Angabe; strukturierte Aktionen außer
    ``raise`` sind Ausdrücke und nicht zugelassen."""
    if value is None:
        return set()
    items = value if isinstance(value, list) else [value]
    names: set[str] = set()
    for item in items:
        if isinstance(item, Mapping):
            if set(item) != {"raise"}:
                raise FsmError(
                    f"Aktion {sorted(item)}: nur raise oder ein Name"
                )
            continue
        if not isinstance(item, str) or not item.isidentifier():
            raise FsmError(
                f"{item!r}: nur Bezeichner, keine Ausdrücke"
            )
        names.add(item)
    return names


def _check_names(where: str, used: set[str], ops: type) -> None:
    offered = {
        name
        for name in dir(ops)
        if not name.startswith("_") and callable(getattr(ops, name))
    }
    missing = sorted(used - offered)
    foreign = sorted(offered - used)
    if missing or foreign:
        raise FsmError(
            f"{where}: Namen passen nicht zu {ops.__name__} "
            f"(fehlt: {', '.join(missing) or '-'}; "
            f"ungenutzt: {', '.join(foreign) or '-'})"
        )


def _check_raises(doc: Mapping[str, object]) -> None:
    """Jedes mit ``raise`` erzeugte Ereignis braucht eine Kante im
    Zielzustand oder einem seiner Vorfahren."""
    states = cast(Mapping, doc["states"])
    parents = dict(_parents(states, None))
    by_id = dict(_items(states))
    for owner, state in _items(states):
        for transition in state.get("transitions", ()):
            target = transition.get("target", owner)
            if target not in by_id:  # History: ihr Elternzustand
                target = parents[target]
            for event in _raised(transition):
                if not _handled(event, target, by_id, parents):
                    raise FsmError(
                        f"{doc.get('name')}: raise {event} in "
                        f"{owner}: keine Kante in {target}"
                    )


def _raised(transition: Mapping) -> Iterator[str]:
    for key in ("before", "on", "after"):
        value = transition.get(key)
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, Mapping) and "raise" in item:
                yield item["raise"]["event"]


def _handled(
    event: str,
    state: str | None,
    by_id: Mapping[str, Mapping],
    parents: Mapping[str, str | None],
) -> bool:
    while state is not None:
        for transition in by_id[state].get("transitions", ()):
            name = transition.get("event")
            if name and (event == name or event.startswith(f"{name}.")):
                return True
        state = parents.get(state)
    return False


def _walk(states: Mapping) -> Iterator[Mapping]:
    for _, state in _items(states):
        yield state


def _items(states: Mapping) -> Iterator[tuple[str, Mapping]]:
    for sid, state in states.items():
        yield sid, state
        yield from _items(state.get("states", {}))


def _parents(
    states: Mapping, parent: str | None
) -> Iterator[tuple[str, str | None]]:
    """Zustand → Elternzustand; History-Pseudozustände zählen als
    Kinder ihres Elternzustands."""
    for sid, state in states.items():
        yield sid, parent
        for history in state.get("history", {}):
            yield history, sid
        yield from _parents(state.get("states", {}), sid)


def _history_ids(states: Mapping) -> Iterator[str]:
    for _, state in _items(states):
        yield from state.get("history", {})


# --- Wiederherstellung ----------------------------------------------


def _check_known(chart: Chart, ids: list[str], label: str) -> None:
    unknown = sorted(set(ids) - set(chart.machine.states_map))
    if unknown:
        raise RecordError(
            f"{label}: unbekannte Zustände {', '.join(unknown)}"
        )


def _history_values(
    chart: Chart, machine: StateChart, record: Mapping[str, object]
) -> dict[str, list]:
    history = cast(Mapping[str, list[str]], record["history"])
    known = set(history_ids(chart))
    for key, ids in history.items():
        if key not in known:
            raise RecordError(f"history.{key}: kein History-Zustand")
        _check_known(chart, ids, f"history.{key}")
    return {
        key: [machine.states_map[i] for i in ids]
        for key, ids in history.items()
    }
