"""Ereignisprotokoll je genommenem Übergang (JSONL, SCXML-Namen).

Jede Zeile ist eine Kante des Ablaufs, wie der Ausführer sie genommen
hat: ``state --event [cond] / actions--> target``. ``seq`` ist die
Laufrevision nach dem Übergang; eine Wiederholung nach einem Absturz
schreibt dieselbe Zeile nicht ein zweites Mal. :func:`check_conformance`
gleicht ein Protokoll gegen den deklarierten Ablauf ab: nützlich, wo
ein Mensch abweichen kann; für ``ki-dev run`` gilt es per Bauweise.

XES (IEEE 1849) wäre nur ein späterer Export; die Felder lassen sich
1:1 abbilden (``state`` → ``concept:name``, ``actor`` → ``org:role``,
``adapter`` → ``org:resource``, ``ts`` → ``time:timestamp``).
"""

from __future__ import annotations

from collections.abc import Iterable

from jsonschema import Draft202012Validator

from ki_dev.flow.model import HISTORY, Flow, Transition, targets

EVENTS_FILE = "events.jsonl"

_NAME = {"type": "string", "minLength": 1, "pattern": r"\S"}
_NAMES = {"type": "array", "items": _NAME}
EVENT_SCHEMA = {
    "type": "object",
    "required": [
        "seq",
        "ts",
        "flow",
        "run",
        "state",
        "event",
        "target",
        "cond",
        "actions",
        "escalation",
        "actor",
        "adapter",
    ],
    "additionalProperties": False,
    "properties": {
        "seq": {"type": "integer", "minimum": 1},
        "ts": _NAME,
        "flow": _NAME,
        "run": _NAME,
        "state": _NAME,
        "event": _NAME,
        "target": _NAME,
        "cond": _NAMES,
        "actions": _NAMES,
        "escalation": {"anyOf": [{"type": "null"}, _NAME]},
        "actor": {"anyOf": [{"type": "null"}, _NAME]},
        "adapter": _NAME,
    },
}
_VALIDATOR = Draft202012Validator(EVENT_SCHEMA)


class EventLogError(ValueError):
    """Protokollzeile verletzt das Schema (Feldpfad, ohne Rohwerte)."""


def event_record(
    *,
    seq: int,
    ts: str,
    flow: Flow,
    run_id: str,
    transition: Transition,
    target: str,
    adapter: str,
) -> dict[str, object]:
    """Geprüfte Zeile für eine genommene Kante; ``target`` ist das
    tatsächliche Ziel (bei ``@history`` der Fortsetzungspunkt)."""
    record = {
        "seq": seq,
        "ts": ts,
        "flow": flow.name,
        "run": run_id,
        "state": transition.source,
        "event": transition.event,
        "target": target,
        "cond": list(transition.cond),
        "actions": list(transition.actions),
        "escalation": transition.escalation,
        "actor": flow.state(transition.source).actor,
        "adapter": adapter,
    }
    validate_record(record)
    return record


def validate_record(record: object) -> None:
    errors = sorted(
        _VALIDATOR.iter_errors(record),
        key=lambda e: list(map(str, e.absolute_path)),
    )
    if errors:
        path = ".".join(map(str, errors[0].absolute_path)) or "$"
        raise EventLogError(f"{path}: {errors[0].validator}")


def check_conformance(
    flow: Flow, records: Iterable[dict[str, object]]
) -> list[str]:
    """Abweichungen vom deklarierten Ablauf; leer heißt konform.

    Jede Zeile muss eine Kante (state, event) mit passendem Ziel sein,
    und jede Zeile beginnt dort, wo die vorige endete."""
    problems: list[str] = []
    previous: str | None = None
    for index, record in enumerate(records):
        state, event = str(record["state"]), str(record["event"])
        target = str(record["target"])
        if previous is not None and state != previous:
            problems.append(
                f"{index}: beginnt in {state}, vorher endete {previous}"
            )
        if not any(
            _reaches(flow, t, target)
            for t in flow.candidates(state, event)
        ):
            problems.append(
                f"{index}: keine Kante {state} --{event}--> {target}"
            )
        previous = target
    return problems


def _reaches(flow: Flow, transition: Transition, target: str) -> bool:
    if transition.target == HISTORY:
        return target in targets(flow, transition)
    return transition.target == target
