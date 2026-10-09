"""Gemeinsames Format aller Abläufe: Zustände und Übergänge als Daten.

Ein Ablauf ist ein erweiterter endlicher Automat (EFSM). Schlüssel und
Bedeutung folgen UML-Zustandsmaschinen und SCXML::

    source --event [cond] / actions--> target

==============  =========================  ============================
TOML-Schlüssel  SCXML / UML                Bedeutung
==============  =========================  ============================
``source``      umschließender ``<state>``  Quellzustand (auch Liste)
``event``       ``event``                  auslösendes Ereignis
``cond``        ``cond`` / ``[guard]``     benannte Wächter (UND, ``!``)
``actions``     ausführbarer Inhalt        benannte Kantenaktionen
``target``      ``target``                 Zielzustand
``@history``    ``<history>``              zurück zum Pausenursprung
==============  =========================  ============================

Der Ablauf legt nur Namen fest (``vocabulary``). Was ein Wächter prüft
und was eine Aktion tut, implementiert der Ausführer; beim Binden prüft
er, dass er genau dieses Vokabular kennt. So bleibt die Topologie Daten
und das Vokabular Code, ohne dass eine Schicht die andere kennt.

Gleiche (``source``, ``event``) sind erlaubt, wenn Wächter sie trennen:
die Kandidaten werden in Dateireihenfolge geprüft, der erste passende
gewinnt. Ein Übergang ohne ``cond`` muss der letzte seiner Gruppe sein,
sonst wäre ein späterer unerreichbar. Passt kein Kandidat, ist das
Ereignis in diesem Zustand nicht erlaubt; einen stillen Standardfall
gibt es nicht.

Struktur prüft JSON Schema, Beziehungen prüfen benannte Funktionen
(Technikleitlinie). Diese Schicht führt nichts aus und importiert
weder Ausführer noch Adapter.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from typing import cast

from jsonschema import Draft202012Validator

from ki_dev.flow.pattern import PatternError, expand
from ki_dev.flow.templates import text

HISTORY = "@history"
PASS = "PASS"
"""Review-Ereignis ohne Befund; jede andere Antwort ist eine
Befundklasse des Ablaufs."""
FINAL_KIND = "final"
WAIT_KIND = "wait"


class Verdict(StrEnum):
    """Urteil, das eine Befundklasse auslöst; die einzige feste Liste.

    Welche Ereignisse ein Reviewer liefern darf, nennt der Ablauf
    (``finding_class``); das Urteil folgt daraus."""

    PASS = "PASS"
    CHANGES = "CHANGES"
    NEEDS_DECISION = "NEEDS_DECISION"
    ESCALATE = "ESCALATE"


class FlowError(ValueError):
    """Ablauf verletzt Schema oder Beziehungen (Programmfehler)."""


@dataclass(frozen=True)
class Turn:
    """Was eine Übergabe ausmacht: Vorlage unter
    ``flow/templates/<ABLAUF>/`` und die Kontextbausteine in ihrer
    Reihenfolge."""

    template: str
    context: tuple[str, ...] = ()


@dataclass(frozen=True)
class Operation:
    """Was der Ausführer beim Betreten eines Zustands tut (Moore).

    ``template`` und ``context`` beschreiben eine Übergabe (``turn``):
    Rollenvorlage unter ``flow/templates/<ABLAUF>/`` und die
    Kontextbausteine in ihrer Reihenfolge; was ein Baustein liefert,
    steckt der Aufrufer unter dem Namen ein."""

    do: str
    cond: tuple[str, ...] = ()
    template: str | None = None
    context: tuple[str, ...] = ()

    @property
    def turn(self) -> Turn | None:
        """Die Übergabe dieser Operation (``None`` ohne Vorlage)."""
        if self.template is None:
            return None
        return Turn(self.template, self.context)


@dataclass(frozen=True)
class State:
    id: str
    kind: str
    actor: str | None = None
    operations: tuple[Operation, ...] = ()


@dataclass(frozen=True)
class Transition:
    source: str
    event: str
    target: str
    cond: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    escalation: str | None = None
    hint: str | None = None
    turn: Turn | None = None
    """Nachricht am Übergang: Vorlage und Kontext, wenn diese Kante die
    Übergabe bestimmt (statt der Operation des Zielzustands)."""


@dataclass(frozen=True)
class Vocabulary:
    kinds: tuple[str, ...]
    events: tuple[str, ...]
    guards: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    escalations: tuple[str, ...] = ()
    operations: tuple[str, ...] = ()
    context: tuple[str, ...] = ()
    required: Mapping[str, tuple[str, ...]] = ()  # type: ignore[assignment]


@dataclass(frozen=True)
class FindingClass:
    verdict: str
    text: str


@dataclass(frozen=True)
class Flow:
    name: str
    start: str
    final: tuple[str, ...]
    vocabulary: Vocabulary
    states: Mapping[str, State]
    transitions: tuple[Transition, ...]
    finding_classes: Mapping[str, FindingClass]
    priority: tuple[str, ...]

    def outgoing(self, state: str) -> tuple[Transition, ...]:
        self.state(state)
        return tuple(t for t in self.transitions if t.source == state)

    def candidates(
        self, state: str, flow_event: str
    ) -> tuple[Transition, ...]:
        """Übergänge für (zustand, ereignis) in Prüfreihenfolge."""
        return tuple(
            t for t in self.outgoing(state) if t.event == flow_event
        )

    def state(self, state: str) -> State:
        try:
            return self.states[state]
        except KeyError:
            raise FlowError(
                f"unbekannter Zustand: {state}"
            ) from None

    # --- Review-Vokabular: PASS und die Befundklassen ---------------

    def review_events(self) -> tuple[str, ...]:
        """Erlaubte Review-Antworten: PASS, dann die Befundklassen in
        Vorrangreihenfolge."""
        return (PASS, *self.priority)

    def verdict(self, event: str) -> Verdict:
        """Urteil zu einem Review-Ereignis."""
        if event == PASS:
            return Verdict.PASS
        if event not in self.finding_classes:
            raise FlowError(f"kein Review-Ereignis: {event}")
        return Verdict(self.finding_classes[event].verdict)

    def events_with(self, verdict: Verdict) -> tuple[str, ...]:
        """Review-Ereignisse mit diesem Urteil, in
        Vorrangreihenfolge."""
        return tuple(
            event
            for event in self.review_events()
            if self.verdict(event) is verdict
        )

    def strongest(self, classes: Iterable[str]) -> str:
        """PASS ohne Befunde, sonst die stärkste Klasse nach
        priority."""
        found = set(classes)
        unknown = found - set(self.priority)
        if unknown:
            raise FlowError(
                f"unbekannte Befundklasse: {', '.join(sorted(unknown))}"
            )
        for name in self.priority:
            if name in found:
                return name
        return PASS

    def unbound_changes_event(self) -> str:
        """Ereignis für CHANGES ohne gültige Kriteriumsbindung: die
        stärkste Klasse mit NEEDS_DECISION (der Mensch klärt)."""
        events = self.events_with(Verdict.NEEDS_DECISION)
        if not events:
            raise FlowError(
                f"{self.name}: keine Befundklasse mit NEEDS_DECISION"
            )
        return events[0]


def load_flow(name: str) -> Flow:
    """Mitgelieferten Ablauf ``ki_dev/flow/<name>.toml`` laden.

    I/O-Grenze: Aufrufer laden einmal und reichen das geprüfte Objekt
    ausdrücklich weiter."""
    resource = files("ki_dev.flow").joinpath(f"{name}.toml")
    try:
        raw = tomllib.loads(resource.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeError) as exc:
        raise FlowError(f"{name}.toml: kein gültiges TOML") from exc
    except FileNotFoundError as exc:
        raise FlowError(f"unbekannter Ablauf: {name}") from exc
    return parse_flow(raw)


def read_raw(name: str) -> dict:
    """Rohdaten eines mitgelieferten Ablaufs (Werkzeuge, Tests)."""
    resource = files("ki_dev.flow").joinpath(f"{name}.toml")
    return tomllib.loads(resource.read_text(encoding="utf-8"))


def parse_flow(raw: object) -> Flow:
    """Muster expandieren, dann Schema, dann Beziehungen prüfen;
    danach Objekte bauen."""
    _check_schema(raw, _PATTERN_VALIDATOR)
    where = f"{cast(dict, raw).get('name')}.toml"
    try:
        table = expand(cast(dict, raw), where)
    except PatternError as exc:
        raise FlowError(str(exc)) from exc
    _check_schema(table)
    flow = Flow(
        name=table["name"],
        start=table["start"],
        final=tuple(table["final"]),
        vocabulary=_vocabulary(
            table["vocabulary"], table.get("required", {})
        ),
        states=_states(table["state"], where),
        transitions=tuple(
            transition
            for item in table["transition"]
            for transition in _transitions(item)
        ),
        finding_classes={
            name: FindingClass(item["verdict"], item["text"])
            for name, item in table.get("finding_class", {}).items()
        },
        priority=tuple(table.get("priority", ())),
    )
    _check_relations(flow, where)
    return flow


def _vocabulary(item: dict, required: dict) -> Vocabulary:
    return Vocabulary(
        kinds=tuple(item["kinds"]),
        events=tuple(item["events"]),
        guards=tuple(item.get("guards", ())),
        actions=tuple(item.get("actions", ())),
        escalations=tuple(item.get("escalations", ())),
        operations=tuple(item.get("operations", ())),
        context=tuple(item.get("context", ())),
        required={
            kind: tuple(events) for kind, events in required.items()
        },
    )


def _states(items: list[dict], where: str) -> dict[str, State]:
    states: dict[str, State] = {}
    for index, item in enumerate(items):
        if item["id"] in states:
            raise FlowError(
                f"{where}: state.{index}.id: doppelt ({item['id']})"
            )
        states[item["id"]] = State(
            id=item["id"],
            kind=item["kind"],
            actor=item.get("actor"),
            operations=tuple(
                _operation(op) for op in item.get("operation", ())
            ),
        )
    return states


def _operation(item: dict) -> Operation:
    return Operation(
        item["do"],
        tuple(item.get("cond", ())),
        item.get("template"),
        tuple(use["use"] for use in item.get("context", ())),
    )


def _transitions(item: dict) -> tuple[Transition, ...]:
    """``source`` als Liste ist dieselbe Kante aus mehreren Zuständen
    (flache Form eines gemeinsamen Elternzustands in SCXML)."""
    sources = (
        item["source"]
        if isinstance(item["source"], list)
        else [item["source"]]
    )
    return tuple(_transition(item, source) for source in sources)


def _transition(item: dict, source: str) -> Transition:
    return Transition(
        source=source,
        event=item["event"],
        target=item["target"],
        cond=tuple(item.get("cond", ())),
        actions=tuple(item.get("actions", ())),
        escalation=item.get("escalation"),
        hint=item.get("hint"),
        turn=_edge_turn(item),
    )


def _edge_turn(item: dict) -> Turn | None:
    if "template" not in item:
        return None
    return Turn(
        item["template"],
        tuple(use["use"] for use in item.get("context", ())),
    )


# --- Schema -----------------------------------------------------------

_TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
_ID = {"type": "string", "pattern": r"^[a-z_]+(\.[a-z_]+)?$"}
_NAME = {"type": "string", "pattern": r"^[A-Za-z_]+$"}
_NAMES = {"type": "array", "uniqueItems": True, "items": _NAME}
_TEMPLATE = {"type": "string", "pattern": r"^[a-z]+(-[a-z]+)*$"}
_CONTEXT = {
    "type": "array",
    "minItems": 1,
    "items": {
        "type": "object",
        "required": ["use"],
        "additionalProperties": False,
        "properties": {"use": _NAME},
    },
}
_GUARDS = {
    "type": "array",
    "minItems": 1,
    "items": {"type": "string", "pattern": r"^!?[A-Za-z_]+$"},
}

_SCHEMA = {
    "type": "object",
    "required": [
        "name",
        "start",
        "final",
        "vocabulary",
        "state",
        "transition",
    ],
    "additionalProperties": False,
    "dependentRequired": {
        "finding_class": ["priority"],
        "priority": ["finding_class"],
    },
    "properties": {
        "name": _ID,
        "start": _ID,
        "final": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": _ID,
        },
        "vocabulary": {
            "type": "object",
            "required": ["kinds", "events"],
            "additionalProperties": False,
            "properties": {
                "kinds": {**_NAMES, "minItems": 1},
                "events": {**_NAMES, "minItems": 1},
                "guards": _NAMES,
                "actions": _NAMES,
                "escalations": _NAMES,
                "operations": _NAMES,
                "context": _NAMES,
            },
        },
        "required": {
            "type": "object",
            "additionalProperties": _NAMES,
        },
        "finding_class": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {
                "type": "object",
                "required": ["verdict", "text"],
                "additionalProperties": False,
                "properties": {
                    "verdict": {
                        "enum": [
                            Verdict.CHANGES,
                            Verdict.NEEDS_DECISION,
                            Verdict.ESCALATE,
                        ]
                    },
                    "text": _TEXT,
                },
            },
        },
        "priority": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": _ID,
        },
        "state": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "kind"],
                "additionalProperties": False,
                "properties": {
                    "id": _ID,
                    "kind": _NAME,
                    "actor": _TEXT,
                    "operation": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["do"],
                            "additionalProperties": False,
                            "properties": {
                                "do": _NAME,
                                "cond": _GUARDS,
                                "template": _TEMPLATE,
                                "context": _CONTEXT,
                            },
                        },
                    },
                },
            },
        },
        "transition": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["source", "event", "target"],
                "additionalProperties": False,
                "properties": {
                    "source": {
                        "anyOf": [
                            _ID,
                            {
                                "type": "array",
                                "minItems": 1,
                                "uniqueItems": True,
                                "items": _ID,
                            },
                        ],
                    },
                    "event": _NAME,
                    "target": {
                        "anyOf": [_ID, {"const": HISTORY}],
                    },
                    "cond": _GUARDS,
                    "actions": {**_NAMES, "minItems": 1},
                    "escalation": _NAME,
                    "hint": _TEXT,
                    "template": _TEMPLATE,
                    "context": _CONTEXT,
                },
                "dependentRequired": {"context": ["template"]},
            },
        },
    },
}
_VALIDATOR = Draft202012Validator(_SCHEMA)

# Muster und Phasen (vor der Expansion geprüft). Ein Musterzustand
# trägt ``local`` statt ``id``; Kanten nennen lokale Namen, ``@next``
# oder globale Zustände.
_STATE_ITEM = _SCHEMA["properties"]["state"]["items"]
_TRANSITION_ITEM = _SCHEMA["properties"]["transition"]["items"]
_PATTERN_STATE = {
    **_STATE_ITEM,
    "required": ["local", "kind"],
    "properties": {
        **{
            k: v
            for k, v in _STATE_ITEM["properties"].items()
            if k != "id"
        },
        "local": _NAME,
    },
}
_PATTERN_TRANSITION = {
    **_TRANSITION_ITEM,
    "properties": {
        **_TRANSITION_ITEM["properties"],
        "source": _NAME,
        "target": {"type": "string", "pattern": r"^@?[a-z_]+$"},
        "template": {
            "type": "string",
            "pattern": r"^@?[a-z]+(-[a-z]+)*$",
        },
    },
}
_PATTERN_SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "extends": _NAME,
                    "globals": _NAMES,
                    "state": {"type": "array", "items": _PATTERN_STATE},
                    "transition": {
                        "type": "array",
                        "items": _PATTERN_TRANSITION,
                    },
                },
            },
        },
        "phase": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "use"],
                "additionalProperties": False,
                "properties": {
                    "id": _NAME,
                    "use": _NAME,
                    "next": _ID,
                    "actor": {
                        "type": "object",
                        "additionalProperties": _TEXT,
                    },
                    "template": {
                        "type": "object",
                        "additionalProperties": _TEMPLATE,
                    },
                    "context": {
                        "type": "object",
                        "additionalProperties": _CONTEXT,
                    },
                    "hint": {
                        "type": "object",
                        "additionalProperties": {
                            "type": "object",
                            "additionalProperties": _TEXT,
                        },
                    },
                },
            },
        },
    },
    "dependentRequired": {"phase": ["pattern"]},
}
_PATTERN_VALIDATOR = Draft202012Validator(_PATTERN_SCHEMA)


def _check_schema(
    raw: object, validator: Draft202012Validator = _VALIDATOR
) -> None:
    errors = sorted(
        validator.iter_errors(raw), key=lambda e: list(e.absolute_path)
    )
    if errors:
        error = errors[0]
        name = raw.get("name") if isinstance(raw, dict) else None
        where = f"{name}.toml" if isinstance(name, str) else "Ablauf"
        path = ".".join(map(str, error.absolute_path)) or "$"
        raise FlowError(f"{where}: {path}: {error.validator}")


# --- Beziehungen (außerhalb des Schemas) ------------------------------


def _check_relations(flow: Flow, where: str) -> None:
    _check_kinds(flow, where)
    _check_classes(flow, where)
    _check_endpoints(flow, where)
    _check_operations(flow, where)
    _check_transitions(flow, where)
    _check_guard_order(flow, where)
    _check_required_events(flow, where)
    _check_end_reachable(flow, where)


def _check_kinds(flow: Flow, where: str) -> None:
    known = set(flow.vocabulary.kinds)
    if FINAL_KIND not in known:
        raise FlowError(
            f"{where}: vocabulary.kinds: {FINAL_KIND} fehlt"
        )
    for state in flow.states.values():
        if state.kind not in known:
            raise FlowError(
                f"{where}: state {state.id}: unbekannte kind "
                f"{state.kind}"
            )
    for kind in flow.vocabulary.required:
        if kind not in known:
            raise FlowError(
                f"{where}: required.{kind}: unbekannte kind"
            )


def _check_classes(flow: Flow, where: str) -> None:
    if set(flow.priority) != set(flow.finding_classes):
        raise FlowError(
            f"{where}: priority: muss genau die Befundklassen nennen"
        )


def _check_endpoints(flow: Flow, where: str) -> None:
    for field, state in (
        ("start", flow.start),
        *(("final", end) for end in flow.final),
    ):
        if state not in flow.states:
            raise FlowError(
                f"{where}: {field}: unbekannter Zustand {state}"
            )
    for state in flow.states.values():
        is_end = state.id in flow.final
        if is_end != (state.kind == FINAL_KIND):
            raise FlowError(
                f"{where}: state {state.id}: kind {FINAL_KIND} genau "
                "für die Zustände in ende"
            )


def _names(guards: Iterable[str]) -> set[str]:
    return {guard.removeprefix("!") for guard in guards}


def _require_template(flow: str, name: str, label: str) -> None:
    """Die Rollenvorlage muss als Datei vorliegen (Ladefehler früh)."""
    try:
        text(flow, name)
    except FileNotFoundError as exc:
        raise FlowError(
            f"{label}.template: Vorlage {flow}/{name}.txt fehlt"
        ) from exc


def _check_operations(flow: Flow, where: str) -> None:
    vocabulary = flow.vocabulary
    for state in flow.states.values():
        for index, op in enumerate(state.operations):
            label = f"{where}: state {state.id}: operation.{index}"
            if op.do not in vocabulary.operations:
                raise FlowError(
                    f"{label}: unbekannte Operation {op.do}"
                )
            _require_known(
                _names(op.cond),
                vocabulary.guards,
                f"{label}.cond",
                "Wächter",
            )
            _require_known(
                set(op.context),
                vocabulary.context,
                f"{label}.context",
                "Kontextbausteine",
            )
            if op.template is not None:
                _require_template(flow.name, op.template, label)
            last = index == len(state.operations) - 1
            if not op.cond and not last:
                raise FlowError(
                    f"{label}: ohne cond nur als letzte Operation"
                )


def _check_transitions(flow: Flow, where: str) -> None:
    vocabulary = flow.vocabulary
    events = set(vocabulary.events)
    for index, t in enumerate(flow.transitions):
        label = f"{where}: transition.{index}"
        _require_state(flow, t.source, f"{label}.source")
        if t.target == HISTORY:
            if flow.state(t.source).kind != WAIT_KIND:
                raise FlowError(
                    f"{label}.target: {HISTORY} nur aus kind "
                    f"{WAIT_KIND}"
                )
        else:
            _require_state(flow, t.target, f"{label}.target")
        if t.event not in events:
            raise FlowError(
                f"{label}.bei: unbekanntes Ereignis {t.event}"
            )
        _require_known(
            _names(t.cond),
            vocabulary.guards,
            f"{label}.cond",
            "Wächter",
        )
        _require_known(
            set(t.actions),
            vocabulary.actions,
            f"{label}.actions",
            "Aktion",
        )
        if t.escalation is not None:
            _require_known(
                {t.escalation},
                vocabulary.escalations,
                f"{label}.escalation",
                "Eskalation",
            )
        if t.turn is not None:
            _require_known(
                set(t.turn.context),
                vocabulary.context,
                f"{label}.context",
                "Kontextbausteine",
            )
            _require_template(flow.name, t.turn.template, label)


def _require_state(flow: Flow, state: str, label: str) -> None:
    if state not in flow.states:
        raise FlowError(f"{label}: unbekannter Zustand {state}")


def _require_known(
    names: set[str], known: Iterable[str], label: str, kind: str
) -> None:
    unknown = sorted(names - set(known))
    if unknown:
        raise FlowError(
            f"{label}: unbekannte {kind} {', '.join(unknown)}"
        )


def _check_guard_order(flow: Flow, where: str) -> None:
    """Gleiche (von, bei) nur mit Wächtern; ungeschützt zuletzt."""
    groups: dict[tuple[str, str], list[Transition]] = {}
    for t in flow.transitions:
        groups.setdefault((t.source, t.event), []).append(t)
    for (source, event), group in groups.items():
        for t in group[:-1]:
            if not t.cond:
                raise FlowError(
                    f"{where}: doppelter Übergang {source} bei {event}"
                )


def _check_required_events(flow: Flow, where: str) -> None:
    required = flow.vocabulary.required
    for state in flow.states.values():
        present = {t.event for t in flow.outgoing(state.id)}
        missing = set(required.get(state.kind, ())) - present
        if missing:
            raise FlowError(
                f"{where}: state {state.id}: fehlende Ereignisse "
                f"{', '.join(sorted(missing))}"
            )
        if state.kind == FINAL_KIND and present:
            raise FlowError(
                f"{where}: state {state.id}: Ende ohne Übergänge"
            )


def targets(flow: Flow, transition: Transition) -> set[str]:
    """Mögliche Ziele; ``@history`` steht für jeden Zustand,
    aus dem eine Kante in den wartenden Zustand führt."""
    if transition.target != HISTORY:
        return {transition.target}
    return {
        t.source
        for t in flow.transitions
        if t.target == transition.source
    }


def reaching_final(flow: Flow) -> set[str]:
    """Zustände, von denen aus ein Ende erreichbar ist (rückwärts)."""
    reached = set(flow.final)
    changed = True
    while changed:
        changed = False
        for t in flow.transitions:
            if t.source not in reached and targets(flow, t) & reached:
                reached.add(t.source)
                changed = True
    return reached


def _check_end_reachable(flow: Flow, where: str) -> None:
    dead = sorted(set(flow.states) - reaching_final(flow))
    if dead:
        raise FlowError(
            f"{where}: Sackgasse ohne Weg zu {', '.join(flow.final)}: "
            f"{', '.join(dead)}"
        )
