"""Grenzwerte eines Laufs als Daten (Regel 4: Grenzwert =
Profil-Daten).

``limits`` hat drei Teile: ``run`` (laufweit) und ``role`` (je Rolle
des Ablaufs) mit Standardwerten und Schema des Gerüsts, ``flow`` mit
Standardwerten und Schema des Pakets. Der Ausführer setzt sie beim
Start einmal (:func:`resolve`), speichert sie im Datensatz, und das
Modell liest sie (``RunModel.limits``); verglichen wird in Wächtern.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

from ki_dev.flow.binding import BindingError, validate

RUN_DEFAULTS = {
    "max_agent_calls": 6,
    "max_total_tokens": 1_000_000,
    "max_claude_cost_usd": 3.0,
    "min_remaining_percent": 10.0,
    "process_retries": 3,
    "protocol_attempts": 3,
}
ROLE_DEFAULTS = {
    "max_context_tokens": 80_000,
    "max_usage_delta_percentage_points": 20.0,
}
EMPTY_FLOW_SCHEMA = {"type": "object", "additionalProperties": False}
"""Schema der Ablaufgrenzen eines Pakets ohne eigene Grenzen."""

COUNT = {"type": "integer", "minimum": 1}
PERCENT = {"type": "number", "minimum": 0, "exclusiveMaximum": 100}
POSITIVE = {"type": "number", "exclusiveMinimum": 0}
RUN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": list(RUN_DEFAULTS),
    "properties": {
        "max_agent_calls": COUNT,
        "max_total_tokens": COUNT,
        "max_claude_cost_usd": POSITIVE,
        "min_remaining_percent": PERCENT,
        "process_retries": COUNT,
        "protocol_attempts": COUNT,
    },
}
ROLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": list(ROLE_DEFAULTS),
    "properties": {
        "max_context_tokens": COUNT,
        # wie TurnBudget: in (0, 100] Prozentpunkten
        "max_usage_delta_percentage_points": {
            "type": "number",
            "exclusiveMinimum": 0,
            "maximum": 100,
        },
    },
}


def resolve(
    given: Mapping,
    roles: Iterable[str],
    flow_defaults: Mapping,
    flow_schema: Mapping,
) -> dict:
    """``given`` mit den Standardwerten aufgefüllt und geprüft. Ein
    Fehler nennt den Pfad (``limits.run.foo``), nie den Wert."""
    roles = sorted(set(roles))
    _known(given, ("run", "role", "flow"), "limits")
    run = _part(given, "run", RUN_DEFAULTS, "limits")
    flow = _part(given, "flow", flow_defaults, "limits")
    role_given = _object(given.get("role", {}), "limits.role")
    _known(role_given, roles, "limits.role")
    role = {
        name: _part(role_given, name, ROLE_DEFAULTS, "limits.role")
        for name in roles
    }
    limits = {"run": run, "role": role, "flow": flow}
    validate(limits, _schema(roles, flow_schema), "limits")
    _finite(limits, "limits")
    return limits


def _part(
    given: Mapping, name: str, defaults: Mapping, where: str
) -> dict:
    values = _object(given.get(name, {}), f"{where}.{name}")
    _known(values, defaults, f"{where}.{name}")
    return {**defaults, **values}


def _object(value: object, where: str) -> Mapping:
    if not isinstance(value, Mapping):
        raise BindingError(f"{where}: type")
    return value


def _known(values: Mapping, names: Iterable[str], where: str) -> None:
    """Unbekannte Schlüssel mit ihrem Pfad melden (das Schema nennt
    bei ``additionalProperties`` nur das umgebende Objekt)."""
    unknown = sorted(set(map(str, values)) - set(names))
    if unknown:
        raise BindingError(
            f"{where}.{unknown[0]}: additionalProperties"
        )


def _finite(value: object, where: str) -> None:
    """JSON Schema lässt inf und nan durch; Grenzen sind endlich."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            _finite(item, f"{where}.{key}")
    elif isinstance(value, float) and not math.isfinite(value):
        raise BindingError(f"{where}: finite")


def _schema(roles: list[str], flow_schema: Mapping) -> dict:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["run", "role", "flow"],
        "properties": {
            "run": RUN_SCHEMA,
            "role": {
                "type": "object",
                "additionalProperties": False,
                "required": roles,
                "properties": dict.fromkeys(roles, ROLE_SCHEMA),
            },
            "flow": dict(flow_schema),
        },
    }
