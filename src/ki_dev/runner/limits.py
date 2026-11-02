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
    "max_fresh_tokens": 1_000_000,
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
        "max_fresh_tokens": COUNT,
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


MEASUREMENT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["role"],
    "properties": {
        "role": {"type": "string", "minLength": 1},
        "context": {"type": ["integer", "null"], "minimum": 0},
        "quota_left": {
            "type": ["number", "null"],
            "minimum": 0,
            "maximum": 100,
            "finite": True,
        },
        "quota_delta": {
            "type": ["number", "null"],
            "minimum": 0,
            "finite": True,
        },
        "calls": {"type": ["integer", "null"], "minimum": 0},
        "tokens": {"type": ["integer", "null"], "minimum": 0},
        "cost_usd": {
            "type": ["number", "null"],
            "minimum": 0,
            "finite": True,
        },
        "gaps": {
            "type": "array",
            "items": {"type": "string", "minLength": 1},
        },
    },
}
"""Nutzlast des Ereignisses ``measured``. Ein Feld ``None`` (oder
fehlend) ist nicht gemessen: der Executor deklariert die Messung
nicht."""


def limit_reasons(measurement: Mapping, limits: Mapping) -> list[str]:
    """Alle erreichten Grenzen, keine Kurzschlussauswertung; leer,
    wenn die Messung unter allen Grenzen liegt. Rein."""
    run = limits["run"]
    invalid = _nonfinite_fields(measurement)
    invalid.extend(_nonfinite_fields(limits, "limits"))
    if invalid:
        return [f"Messluecke: ungueltiger Messwert {invalid[0]}"]
    role = measurement["role"]
    # Rolle ohne eigene Grenzen (nicht im Ablauf): Standardwerte
    own = limits["role"].get(role, ROLE_DEFAULTS)
    context = measurement.get("context")
    left = measurement.get("quota_left")
    delta = measurement.get("quota_delta")
    calls = measurement.get("calls")
    tokens = measurement.get("tokens")
    cost = measurement.get("cost_usd")
    reasons = []
    if context is not None and context >= own["max_context_tokens"]:
        reasons.append(
            f"Kontextgrenze erreicht für {role}: gemessen {context} "
            f">= Grenze {own['max_context_tokens']}"
        )
    if left is not None and left < run["min_remaining_percent"]:
        reasons.append(
            f"Kontingentreserve unterschritten für {role}: "
            f"{left:g} % < {run['min_remaining_percent']:g} %"
        )
    allowed = own["max_usage_delta_percentage_points"]
    if delta is not None and delta >= allowed:
        reasons.append(
            f"Aufgaben-Delta-Budget erreicht für {role}: beobachteter "
            f"kontoweiter Verbrauch seit Rollenbaseline im aktuellen "
            f"Fenster {delta:g} Prozentpunkte >= Budget {allowed:g}"
        )
    if calls is not None and calls >= run["max_agent_calls"]:
        reasons.append(f"Aufrufgrenze erreicht: {calls}")
    if tokens is not None and tokens >= run["max_fresh_tokens"]:
        reasons.append(f"Token-Grenze erreicht: {tokens}")
    if cost is not None and cost >= run["max_claude_cost_usd"]:
        reasons.append(f"Claude-Kostengrenze erreicht: {cost:g} USD")
    reasons.extend(measurement.get("gaps") or ())
    return reasons


def _nonfinite_fields(
    value: object, where: str = "measurement"
) -> list[str]:
    """Reject non-finite numeric measurements before comparisons.

    JSON Schema implementations commonly accept NaN and infinity for a
    ``number``; those values must never turn a measurement into a pass.
    """
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            found.extend(_nonfinite_fields(item, f"{where}.{key}"))
    elif isinstance(value, float) and not math.isfinite(value):
        found.append(where)
    return found


def _finite_schema(schema: object) -> object:
    """Add an explicit finite-number annotation throughout a schema."""
    if isinstance(schema, Mapping):
        result = {
            key: _finite_schema(value) for key, value in schema.items()
        }
        if result.get("type") == "number" or (
            isinstance(result.get("type"), list)
            and "number" in result["type"]
        ):
            result["finite"] = True
        return result
    if isinstance(schema, list):
        return [_finite_schema(item) for item in schema]
    return schema


MEASUREMENT_SCHEMA = _finite_schema(MEASUREMENT_SCHEMA)
