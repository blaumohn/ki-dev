"""Datensatz eines Laufs (``record.json``).

Ein Dokument je Lauf, nach jedem Schritt atomar ersetzt
(``RunStore.save_record``): Konfiguration der Lauf-Maschine
(:mod:`ki_dev.fsm`), ihre offene Operation und die Laufdaten, darin der
Ablaufzustand im Vertrag von ``machine.state_json``. Die Form prüft
JSON Schema (Technikleitlinie); Zustände prüft die Lauf-Maschine beim
Wiederherstellen.
"""

from __future__ import annotations

from typing import TypedDict, cast

from jsonschema import Draft202012Validator

from ki_dev.fsm import RECORD_SCHEMA
from ki_dev.runner.machine import decode_run_state
from ki_dev.runner.run_machine import Operation, RunMachine

SCHEMA_VERSION = 2


class RunData(TypedDict):
    """Laufdaten neben den Maschinen."""

    run_state: dict[str, object]
    task: dict[str, object]
    round_id: int
    review_sequence: int
    open_objection: str | None
    round_base: object | None
    run_base: object | None
    work_report: str | None
    evidence: dict[str, object] | None
    reviewed_refs: dict[str, object] | None
    frozen_result: dict[str, object] | None
    final_result: dict[str, object] | None
    decision: dict[str, object] | None
    decision_answer: str | None
    last_error: str | None


class RunRecordError(ValueError):
    """Datensatz verletzt sein Schema (Feldpfad, ohne Rohwerte)."""


_TEXT = {"type": "string", "minLength": 1}
_OBJECT = {"type": "object"}


def _nullable(schema: dict) -> dict:
    return {"anyOf": [{"type": "null"}, schema]}


_PENDING = {
    "type": "object",
    "required": ["id", "kind", "repeatable", "call_id"],
    "additionalProperties": False,
    "properties": {
        "id": _TEXT,
        "kind": _TEXT,
        "repeatable": {"type": "boolean"},
        "call_id": _nullable(_TEXT),
    },
}
_DATA_PROPERTIES = {
    "run_state": _OBJECT,
    "task": _OBJECT,
    "round_id": {"type": "integer", "minimum": 1},
    "review_sequence": {"type": "integer", "minimum": 0},
    "open_objection": _nullable({"type": "string"}),
    "round_base": {},
    "run_base": {},
    "work_report": _nullable({"type": "string"}),
    "evidence": _nullable(_OBJECT),
    "reviewed_refs": _nullable(_OBJECT),
    "frozen_result": _nullable(_OBJECT),
    "final_result": _nullable(_OBJECT),
    "decision": _nullable(_OBJECT),
    "decision_answer": _nullable({"type": "string"}),
    "last_error": _nullable({"type": "string"}),
}
SCHEMA = {
    "type": "object",
    "required": ["schema_version", "run", "pending", "data"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": SCHEMA_VERSION},
        "run": RECORD_SCHEMA,
        "pending": _nullable(_PENDING),
        "data": {
            "type": "object",
            "required": list(_DATA_PROPERTIES),
            "additionalProperties": False,
            "properties": _DATA_PROPERTIES,
        },
    },
}
_VALIDATOR = Draft202012Validator(SCHEMA)


def encode_record(
    machine: RunMachine, data: RunData
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "run": machine.record,
        "pending": machine.pending,
        "data": dict(data),
    }


def decode_record(document: object) -> tuple[RunMachine, RunData]:
    """Form prüfen, Ablaufzustand und Lauf-Maschine wiederherstellen."""
    _check(document)
    fields = cast(dict[str, object], document)
    data = cast(RunData, fields["data"])
    run = decode_run_state(data["run_state"])
    machine = RunMachine(
        cast(dict[str, object], fields["run"]),
        cast(Operation | None, fields["pending"]),
        run.state,
    )
    return machine, data


def _check(document: object) -> None:
    errors = sorted(
        _VALIDATOR.iter_errors(document),
        key=lambda e: list(map(str, e.absolute_path)),
    )
    if errors:
        error = errors[0]
        path = ".".join(map(str, error.absolute_path)) or "$"
        raise RunRecordError(f"{path}: {error.validator}")
