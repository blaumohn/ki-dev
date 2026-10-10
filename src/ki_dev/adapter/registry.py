"""Executoren des Gerüsts: Name → Transport und deklarierte Messungen.

Der Transport ist Code je Anbieter und nennt in ``capabilities``, was
er messen kann. Der Executor ist Daten (``executors.toml``): er bindet
einen Namen an einen Transport und deklariert die Messungen, die der
Ausführer verlangt. Beim Laden gilt wie bei ``bind`` für Abläufe:
``measures`` ⊆ Fähigkeiten des Transports, sonst ein Fehler.

    [executor.manual]  transport = "console", measures = ["quota"]
    → executor.manual.measures: Transport console misst kein quota
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from functools import cache
from importlib.resources import files

from jsonschema import Draft202012Validator

from ki_dev.adapter import manual, mock
from ki_dev.adapter.executors import (
    ExecutorSpec,
    Measure,
    cli_transports,
)

DECLARATIONS = "executors.toml"


class ExecutorConfigError(ValueError):
    """Executor-Deklaration verletzt Schema oder Transportfähigkeit."""


def transport_capabilities() -> dict[str, frozenset[Measure]]:
    """Was jeder Transport messen kann, aus seinem Code."""
    table = {
        name: adapter.capabilities
        for name, adapter in cli_transports().items()
    }
    table[manual.CONSOLE] = manual.CAPABILITIES
    table[manual.INBOX] = manual.CAPABILITIES
    table[mock.NAME] = mock.CAPABILITIES
    return table


@cache
def executor_specs() -> Mapping[str, ExecutorSpec]:
    """Die Executoren des Gerüsts, einmal geladen und geprüft."""
    resource = files("ki_dev.adapter").joinpath(DECLARATIONS)
    raw = tomllib.loads(resource.read_text(encoding="utf-8"))
    return parse_executors(raw)


def parse_executors(raw: object) -> dict[str, ExecutorSpec]:
    """Schema, dann Fähigkeiten prüfen; Fehler nennen den Feldpfad."""
    _check_schema(raw)
    declared = raw["executor"]  # type: ignore[index]
    capabilities = transport_capabilities()
    specs: dict[str, ExecutorSpec] = {}
    for name, item in declared.items():
        specs[name] = _spec(name, item, capabilities)
    return specs


def _spec(
    name: str,
    item: Mapping[str, object],
    capabilities: Mapping[str, frozenset[Measure]],
) -> ExecutorSpec:
    transport = str(item["transport"])
    if transport not in capabilities:
        known = ", ".join(sorted(capabilities))
        raise ExecutorConfigError(
            f"executor.{name}.transport: unbekannt {transport!r}; "
            f"bekannt: {known}"
        )
    measures = frozenset(
        Measure(value) for value in item["measures"]  # type: ignore[union-attr]
    )
    missing = sorted(measures - capabilities[transport])
    if missing:
        raise ExecutorConfigError(
            f"executor.{name}.measures: Transport {transport} misst "
            f"kein {', '.join(missing)}"
        )
    return ExecutorSpec(name, transport, measures)


_SCHEMA = {
    "type": "object",
    "required": ["executor"],
    "additionalProperties": False,
    "properties": {
        "executor": {
            "type": "object",
            "minProperties": 1,
            "propertyNames": {"pattern": "^[a-z][a-z0-9-]*$"},
            "additionalProperties": {
                "type": "object",
                "required": ["transport", "measures"],
                "additionalProperties": False,
                "properties": {
                    "transport": {"type": "string", "pattern": r"\S"},
                    "measures": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"enum": [m.value for m in Measure]},
                    },
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
        raise ExecutorConfigError(
            f"{DECLARATIONS}: {path}: {error.validator}"
        )
