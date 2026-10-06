"""Deklarative Zustandstabelle für ``ki-dev step`` (step-flow.toml).

Die Tabelle ist mitgelieferte Paketdatei wie tool-versions.json: Daten
statt fest verdrahteter Folgetexte (Programmierleitlinie: umfangreiche
Daten aus dem Programmcode auslagern). Die Struktur prüft ein JSON
Schema, die Beziehungen (Ziele vorhanden, Pflichtereignisse,
Erreichbarkeit des Endes) prüfen benannte Funktionen
(Technikleitlinie). ki-dev führt nichts automatisch aus; die Tabelle
liefert nur Hinweise für den Menschen und die Bedeutung der
Befundklassen.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.resources import files
from typing import cast

from jsonschema import Draft202012Validator

FILE_NAME = "step-flow.toml"

PASS = "PASS"
WRITER_DONE = "erledigt"
DECISION_EVENTS = ("annehmen", "korrigieren", "quelle")
_OTHER_EVENTS = ("importiert", "vorlauf_rot")
_VERDICTS = ("CHANGES", "NEEDS_DECISION")
_KINDS = (
    "schreiben",
    "review",
    "korrektur",
    "entscheidung",
    "quelle",
    "ende",
)


class StepFlowError(ValueError):
    """Tabelle verletzt Schema oder Beziehungen (Programmfehler)."""


@dataclass(frozen=True)
class FindingClass:
    verdict: str
    text: str


@dataclass(frozen=True)
class State:
    id: str
    kind: str
    who: str


@dataclass(frozen=True)
class Transition:
    source: str
    event: str
    target: str
    command: str


@dataclass(frozen=True)
class StepFlow:
    start: str
    end: str
    precedence: tuple[str, ...]
    classes: Mapping[str, FindingClass]
    states: Mapping[str, State]
    transitions: tuple[Transition, ...]

    def outgoing(self, state: str) -> tuple[Transition, ...]:
        self._require_state(state)
        return tuple(t for t in self.transitions if t.source == state)

    def review_event(self, classes: Iterable[str]) -> str:
        """PASS ohne Befunde, sonst die stärkste Klasse nach vorrang."""
        found = set(classes)
        unknown = found - set(self.precedence)
        if unknown:
            raise StepFlowError(
                f"unbekannte Befundklasse: {', '.join(sorted(unknown))}"
            )
        for name in self.precedence:
            if name in found:
                return name
        return PASS

    def verdict(self, event: str) -> str:
        """Review-Urteil zu PASS oder einer Befundklasse."""
        if event == PASS:
            return PASS
        if event not in self.classes:
            raise StepFlowError(f"kein Review-Ereignis: {event}")
        return self.classes[event].verdict

    def events_for_verdict(self, verdict: str) -> tuple[str, ...]:
        """Review-Ereignisse zu einem Urteil: PASS selbst, sonst die
        Befundklassen mit diesem Urteil (in Vorrangreihenfolge)."""
        if verdict == PASS:
            return (PASS,)
        events = tuple(
            name
            for name in self.precedence
            if self.classes[name].verdict == verdict
        )
        if not events:
            raise StepFlowError(f"kein Urteil der Tabelle: {verdict}")
        return events

    def hint_lines(
        self,
        state: str,
        bead: str,
        events: Iterable[str] | None = None,
    ) -> list[str]:
        """Hinweisblock für den Menschen mit eingesetzter Bead-ID;
        ``events`` beschränkt ihn auf die Übergänge eines Urteils."""
        wanted = None if events is None else set(events)
        lines = [
            f"Hinweis für den Menschen: Zustand {state}; Folgeschritte "
            f"laut {FILE_NAME} (nichts läuft automatisch):"
        ]
        for transition in self.outgoing(state):
            if wanted is not None and transition.event not in wanted:
                continue
            command = transition.command.replace("{bead}", bead)
            lines.append(
                f"- {transition.event} → {transition.target}: {command}"
            )
        return lines

    def class_lines(self) -> list[str]:
        """Befundklassen für Review-Rollen, in Vorrangreihenfolge."""
        parts = [
            f"{name} = {self.classes[name].text} "
            f"({self.classes[name].verdict})"
            for name in self.precedence
        ]
        return [
            "Befundklassen: " + "; ".join(parts) + ".",
            "Nenne je Befund seine Klasse; das Urteil folgt der "
            f"stärksten Klasse ({' > '.join(self.precedence)}), "
            "ohne Befund PASS.",
        ]

    def _require_state(self, state: str) -> None:
        if state not in self.states:
            raise StepFlowError(f"unbekannter Zustand: {state}")


def load_step_flow() -> StepFlow:
    """Mitgelieferte Tabelle laden und vollständig prüfen.

    I/O-Grenze: Aufrufer (CLI) laden einmal je Aufruf und übergeben den
    geprüften StepFlow ausdrücklich an die Renderer."""
    resource = files("ki_dev").joinpath(FILE_NAME)
    try:
        raw = tomllib.loads(resource.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeError) as exc:
        raise StepFlowError(f"{FILE_NAME}: kein gültiges TOML") from exc
    return parse_step_flow(raw)


def parse_step_flow(raw: object) -> StepFlow:
    """Erst Schema, dann Beziehungen prüfen; danach Objekte bauen."""
    _check_schema(raw)
    table = cast(dict, raw)
    flow = StepFlow(
        start=table["start"],
        end=table["ende"],
        precedence=tuple(table["vorrang"]),
        classes={
            name: FindingClass(item["urteil"], item["text"])
            for name, item in table["befundklasse"].items()
        },
        states=_states(table["zustand"]),
        transitions=tuple(
            Transition(t["von"], t["bei"], t["nach"], t["befehl"])
            for t in table["uebergang"]
        ),
    )
    _check_relations(flow)
    return flow


# --- Schema -----------------------------------------------------------

_TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
_ID = {"type": "string", "pattern": r"^[a-z_]+(\.[a-z_]+)?$"}

_SCHEMA = {
    "type": "object",
    "required": [
        "start",
        "ende",
        "vorrang",
        "befundklasse",
        "zustand",
        "uebergang",
    ],
    "additionalProperties": False,
    "properties": {
        "start": _ID,
        "ende": _ID,
        "vorrang": {
            "type": "array",
            "minItems": 1,
            "uniqueItems": True,
            "items": _ID,
        },
        "befundklasse": {
            "type": "object",
            "minProperties": 1,
            "additionalProperties": {
                "type": "object",
                "required": ["urteil", "text"],
                "additionalProperties": False,
                "properties": {
                    "urteil": {"enum": list(_VERDICTS)},
                    "text": _TEXT,
                },
            },
        },
        "zustand": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "art", "wer"],
                "additionalProperties": False,
                "properties": {
                    "id": _ID,
                    "art": {"enum": list(_KINDS)},
                    "wer": _TEXT,
                },
            },
        },
        "uebergang": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["von", "bei", "nach", "befehl"],
                "additionalProperties": False,
                "properties": {
                    "von": _ID,
                    "bei": _TEXT,
                    "nach": _ID,
                    "befehl": _TEXT,
                },
            },
        },
    },
}
_VALIDATOR = Draft202012Validator(_SCHEMA)


def _check_schema(raw: object) -> None:
    errors = sorted(
        _VALIDATOR.iter_errors(raw), key=lambda e: list(e.absolute_path)
    )
    if errors:
        error = errors[0]
        path = ".".join(map(str, error.absolute_path)) or "$"
        raise StepFlowError(f"{FILE_NAME}: {path}: {error.validator}")


def _states(items: list[dict]) -> dict[str, State]:
    states: dict[str, State] = {}
    for index, item in enumerate(items):
        state_id = item["id"]
        if state_id in states:
            raise StepFlowError(
                f"{FILE_NAME}: zustand.{index}.id: doppelt ({state_id})"
            )
        states[item["id"]] = State(item["id"], item["art"], item["wer"])
    return states


# --- Beziehungen (außerhalb des Schemas) ------------------------------


def _check_relations(flow: StepFlow) -> None:
    _check_classes(flow)
    _check_endpoints(flow)
    _check_transitions(flow)
    _check_required_events(flow)
    _check_end_reachable(flow)


def _check_classes(flow: StepFlow) -> None:
    if set(flow.precedence) != set(flow.classes):
        raise StepFlowError(
            f"{FILE_NAME}: vorrang: muss genau die Befundklassen nennen"
        )


def _check_endpoints(flow: StepFlow) -> None:
    for field, state in (("start", flow.start), ("ende", flow.end)):
        if state not in flow.states:
            raise StepFlowError(
                f"{FILE_NAME}: {field}: unbekannter Zustand {state}"
            )
    if flow.states[flow.end].kind != "ende":
        raise StepFlowError(f"{FILE_NAME}: ende: Zustand ohne art ende")


def _check_transitions(flow: StepFlow) -> None:
    events = {
        PASS,
        WRITER_DONE,
        *flow.classes,
        *DECISION_EVENTS,
        *_OTHER_EVENTS,
    }
    seen: set[tuple[str, str]] = set()
    for index, transition in enumerate(flow.transitions):
        where = f"{FILE_NAME}: uebergang.{index}"
        for field, state in (
            ("von", transition.source),
            ("nach", transition.target),
        ):
            if state not in flow.states:
                raise StepFlowError(
                    f"{where}.{field}: unbekannter Zustand {state}"
                )
        if transition.event not in events:
            raise StepFlowError(
                f"{where}.bei: unbekanntes Ereignis {transition.event}"
            )
        key = (transition.source, transition.event)
        if key in seen:
            raise StepFlowError(
                f"{where}: doppelter Übergang {key[0]} bei {key[1]}"
            )
        seen.add(key)


def _required_events(flow: StepFlow, kind: str) -> set[str]:
    """Pflichtereignisse je Zustandsart."""
    return {
        "schreiben": {WRITER_DONE},
        "review": {PASS, *flow.classes},
        "korrektur": {WRITER_DONE},
        "entscheidung": set(DECISION_EVENTS),
        "quelle": {"importiert"},
        "ende": set(),
    }[kind]


def _check_required_events(flow: StepFlow) -> None:
    for state in flow.states.values():
        present = {t.event for t in flow.outgoing(state.id)}
        missing = _required_events(flow, state.kind) - present
        if missing:
            raise StepFlowError(
                f"{FILE_NAME}: zustand {state.id}: fehlende Ereignisse "
                f"{', '.join(sorted(missing))}"
            )
        if state.kind == "ende" and present:
            raise StepFlowError(
                f"{FILE_NAME}: zustand {state.id}: Ende ohne Übergänge"
            )


def reaching_end(flow: StepFlow) -> set[str]:
    """Zustände, von denen aus das Ende erreichbar ist (rückwärts)."""
    reached = {flow.end}
    changed = True
    while changed:
        changed = False
        for transition in flow.transitions:
            if (
                transition.target in reached
                and transition.source not in reached
            ):
                reached.add(transition.source)
                changed = True
    return reached


def _check_end_reachable(flow: StepFlow) -> None:
    dead = sorted(set(flow.states) - reaching_end(flow))
    if dead:
        raise StepFlowError(
            f"{FILE_NAME}: Sackgasse ohne Weg zu {flow.end}: "
            f"{', '.join(dead)}"
        )
