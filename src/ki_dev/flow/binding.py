"""Bindungsvertrag eines Ablaufs: welche Katalogoperation ein
Zustand nutzt, welche Laufdaten sie liest und welche Ereignisse sie
liefert. Reine Daten und JSON Schema; ausgeführt wird im Ausführer
(:mod:`ki_dev.runner.bound`)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from jsonschema import Draft202012Validator

NAME = {"type": "string", "pattern": r"^[A-Za-z_][A-Za-z_0-9]*$"}
QUALIFIED = {
    "type": "string",
    "pattern": r"^[a-z_][a-z_0-9]*(\.[a-z_][a-z_0-9]*)*$",
}
PATH = {"type": "array", "items": NAME}
PROJECTION = {
    "type": "object",
    "propertyNames": NAME,
    "additionalProperties": PATH,
}
BINDING_SCHEMA = {
    "type": "object",
    "required": ["do", "input", "output"],
    "additionalProperties": False,
    "properties": {
        "do": QUALIFIED,
        "input": {"type": "array", "items": NAME},
        "output": {"oneOf": [NAME, PROJECTION]},
        "payload": PROJECTION,
        "role": NAME,
        "success": NAME,
        "events": {
            "type": "array",
            "items": NAME,
            "minItems": 1,
            "uniqueItems": True,
        },
    },
    "oneOf": [
        {"required": ["success"], "not": {"required": ["events"]}},
        {"required": ["events"], "not": {"required": ["success"]}},
    ],
}
BINDINGS_SCHEMA = {
    "type": "object",
    "propertyNames": NAME,
    "additionalProperties": BINDING_SCHEMA,
}


class BindingError(ValueError):
    """Ungültiger Vertrag, fehlende Bindung oder ungültiges Ergebnis."""


class OperationFailure(RuntimeError):
    """Vom Dienst gemeldetes technisches Scheitern einer Operation."""


def validate(value: object, schema: dict, where: str) -> None:
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda e: list(map(str, e.absolute_path)),
    )
    if errors:
        error = errors[0]
        path = ".".join(map(str, error.absolute_path)) or "$"
        raise BindingError(f"{where}.{path}: {error.validator}")


@dataclass(frozen=True)
class Binding:
    do: str
    input: tuple[str, ...]
    output: str | Mapping[str, list[str]]
    success: str | None = None
    events: tuple[str, ...] = ()
    payload: Mapping[str, list[str]] | None = None
    role: str | None = None

    @property
    def emitted(self) -> tuple[str, ...]:
        return (self.success,) if self.success else self.events


def parse_bindings(raw: object) -> dict[str, Binding]:
    validate(raw, BINDINGS_SCHEMA, "op")
    return {
        name: Binding(
            item["do"],
            tuple(item["input"]),
            item["output"],
            item.get("success"),
            tuple(item.get("events", ())),
            item.get("payload"),
            item.get("role"),
        )
        for name, item in raw.items()
    }


@dataclass(frozen=True)
class OperationSpec:
    """Katalogeintrag: Funktion und JSON-Verträge ihrer Nutzdaten.

    Die Funktion erhält ausschließlich deklarierte Eingaben. Dienste
    werden beim Aufbau des Katalogs gebunden, nie über Laufzustände.
    """

    execute: Callable[..., object]
    input_schema: dict
    output_schema: dict
    normalize: Callable[[object], object] | None = None


def project(value: object, fields: Mapping[str, list[str]]) -> dict:
    """Explizite Feldpfade, keine Ausdrücke oder Auswertung von Code."""
    result = {}
    for name, path in fields.items():
        current = value
        for key in path:
            if not isinstance(current, Mapping) or key not in current:
                raise BindingError(f"output.{name}.{key}: fehlt")
            current = current[key]
        result[name] = current
    return result
