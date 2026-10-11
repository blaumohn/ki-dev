"""FSM-Kern eines Ablaufs im Format von python-statemachine.

Maßgeblich für Zustände und Kanten ist ``[statechart]`` (natives
Format der Bibliothek, :mod:`ki_dev.fsm`). Die Fachschicht (``kind``,
``actor``, ``operation`` je Zustand) steht daneben unter ``[state]``.

:func:`table_of` leitet daraus die flache Sicht ab, die Prüfungen,
Diagramm, Ereignisprotokoll und Projektion lesen: ein Eintrag je
innerstem Zustand, eine Kante je (Zustand, Ereignis, Ziel). Kanten
eines Elternzustands gelten für alle seine inneren Zustände und folgen
deren eigenen (Vorrang der Kinder wie in SCXML). Abgebildet werden:

==============================  ======================================
``[statechart]``                Sicht
==============================  ======================================
``cond`` / ``unless``           ``cond`` (``unless`` als ``!name``)
``before`` / ``on`` / ``after`` ``actions`` (Namen)
``raise escalation.<ursache>``  ``escalation``
Ziel ist ein History-Zustand    ``@history``
Kante ohne Ziel                 keine Kante (Empfänger eines ``raise``)
==============================  ======================================

Die Sicht ist abgeleitet, nicht gepflegt; ein Test vergleicht sie mit
der Kantenwahl der Bibliothek.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping

ESCALATION_EVENT = "escalation"
"""Präfix der mit ``raise`` erzeugten Eskalationsereignisse."""

_ACTION_KEYS = ("before", "on", "after")


class StatechartError(ValueError):
    """``[statechart]`` passt nicht zur Fachschicht."""


def table_of(raw: Mapping, history: str) -> dict:
    """Flache Tabelle (``state``, ``transition``, ``start``,
    ``final``, ``vocabulary``) aus ``[statechart]`` und ``[state]``;
    ``history`` ist der Name des Ziels ``@history`` der Sicht."""
    chart = raw["statechart"]
    states = chart["states"]
    leaves = list(_leaves(states))
    facts = raw["state"]
    if set(facts) != set(leaves):
        missing = sorted(set(leaves) - set(facts))
        foreign = sorted(set(facts) - set(leaves))
        raise StatechartError(
            "state: muss genau die innersten Zustände nennen "
            f"(fehlt: {', '.join(missing) or '-'}; "
            f"fremd: {', '.join(foreign) or '-'})"
        )
    histories = set(_history_ids(states))
    transitions = [
        _transition(item, source, histories, history)
        for source, item in _edges(states)
        if "target" in item
    ]
    by_id = {sid: state for _, sid, state in _walk(states, 0)}
    table = {
        key: raw[key]
        for key in ("name", "ops", "priority", "finding_class")
        if key in raw
    }
    return {
        **table,
        "start": _start(states),
        "final": [sid for sid in leaves if by_id[sid].get("final")],
        "vocabulary": _vocabulary(raw, transitions, facts),
        "state": [{"id": sid, **facts[sid]} for sid in leaves],
        "transition": transitions,
    }


def edge_of(
    chart: Mapping, owner: str, index: int, source: str, history: str
) -> dict:
    """Kante der Sicht zur Kante ``index`` von ``owner``, genommen in
    ``source`` (bei einem Elternzustand einer seiner inneren)."""
    states = chart["states"]
    by_id = {sid: state for _, sid, state in _walk(states, 0)}
    item = by_id[owner]["transitions"][index]
    return _transition(
        item, source, set(_history_ids(states)), history
    )


def _leaves(states: Mapping) -> Iterator[str]:
    for sid, state in states.items():
        if state.get("states"):
            yield from _leaves(state["states"])
        else:
            yield sid


def _edges(
    states: Mapping,
) -> Iterator[tuple[str | list[str], Mapping]]:
    """Kanten in Prüfreihenfolge: erst die der inneren Zustände, dann
    die der Elternzustände, innere Ebenen zuerst."""
    compounds: list[tuple[int, list[str], Mapping]] = []
    for depth, sid, state in _walk(states, 0):
        if state.get("states"):
            compounds.append(
                (depth, list(_leaves(state["states"])), state)
            )
            continue
        for item in state.get("transitions", ()):
            yield sid, item
    for _, leaves, state in sorted(
        compounds, key=lambda entry: -entry[0]
    ):
        for item in state.get("transitions", ()):
            yield leaves, item


def _walk(
    states: Mapping, depth: int
) -> Iterator[tuple[int, str, Mapping]]:
    for sid, state in states.items():
        yield depth, sid, state
        yield from _walk(state.get("states", {}), depth + 1)


def _transition(
    item: Mapping,
    source: str | list[str],
    histories: set[str],
    history: str,
) -> dict:
    target = item["target"]
    edge: dict[str, object] = {
        "source": source,
        "event": item["event"],
        "target": history if target in histories else target,
    }
    cond = [
        *_names(item.get("cond")),
        *(f"!{name}" for name in _names(item.get("unless"))),
    ]
    if cond:
        edge["cond"] = cond
    actions = [
        name for key in _ACTION_KEYS for name in _names(item.get(key))
    ]
    if actions:
        edge["actions"] = actions
    escalations = [
        _cause(event) for key in _ACTION_KEYS
        for event in _raised(item.get(key))
    ]
    if len(escalations) > 1:
        raise StatechartError(
            f"{source} --{item['event']}-->: höchstens eine Eskalation"
        )
    if escalations:
        edge["escalation"] = escalations[0]
    return edge


def _names(value: object) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [item for item in items if isinstance(item, str)]


def _raised(value: object) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [
        item["raise"]["event"]
        for item in items
        if isinstance(item, Mapping) and "raise" in item
    ]


def _cause(event: str) -> str:
    prefix = f"{ESCALATION_EVENT}."
    if not event.startswith(prefix):
        raise StatechartError(
            f"raise {event}: nur {prefix}<ursache> ist vorgesehen"
        )
    return event.removeprefix(prefix)


def _start(states: Mapping) -> str:
    current = states
    while True:
        sid, state = next(
            (sid, state)
            for sid, state in current.items()
            if state.get("initial")
        )
        if not state.get("states"):
            return sid
        current = state["states"]


def _history_ids(states: Mapping) -> Iterator[str]:
    for _, _, state in _walk(states, 0):
        yield from state.get("history", {})


def _vocabulary(
    raw: Mapping, transitions: list[dict], facts: Mapping
) -> dict:
    """Vokabular der Sicht: Arten aus der Fachschicht, alles andere
    so, wie ``[statechart]`` und die Operationen es nutzen."""
    vocabulary = {"kinds": raw["vocabulary"]["kinds"]}
    for key, values in (
        ("events", [t["event"] for t in transitions]),
        (
            "guards",
            [
                name.removeprefix("!")
                for t in transitions
                for name in t.get("cond", ())
            ]
            + [
                name.removeprefix("!")
                for item in facts.values()
                for op in item.get("operation", ())
                for name in op.get("cond", ())
            ],
        ),
        (
            "actions",
            [
                name
                for t in transitions
                for name in t.get("actions", ())
            ],
        ),
        (
            "escalations",
            [t["escalation"] for t in transitions if "escalation" in t],
        ),
        (
            "operations",
            [
                op["do"]
                for item in facts.values()
                for op in item.get("operation", ())
            ],
        ),
    ):
        unique = list(dict.fromkeys(values))
        if unique:
            vocabulary[key] = unique
    return vocabulary
