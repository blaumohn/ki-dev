"""Vertrag der Laufkonfiguration (Profil plus Auftrag) als JSON Schema.

Das Profil ist Kalibrierung des Ablaufs: Rollen, Tests, Grenzen. Damit
später auch ein Agent Profile wählen oder schreiben kann, ist es reine,
geprüfte Daten. Typen, Pflichtfelder und unbekannte Felder prüft das
Schema; Wertebereiche prüfen die Dataclasses (``Limits``,
``TurnBudget`` …), Beziehungen (getrennte Sitzungen) benannte
Funktionen in ``runner.cli``.

Die Felder einer Rolle hängen am Transport ihres Executors:

    [worker] executor = "claude"   → model, effort, optional
                                     session_id (ohne: neue Sitzung), …
    [review] executor = "mock"     → optional answers, file
    [review] executor = "manual"   → keine weiteren Felder

Fehler nennen den Feldpfad, nie den Wert:
``worker.timeout_s: type``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import MISSING, fields
from functools import cache

from jsonschema import Draft202012Validator, ValidationError

from ki_dev.adapter import manual, mock
from ki_dev.adapter.executors import (
    Access,
    Effort,
    ExecutorSpec,
    cli_transports,
)
from ki_dev.adapter.executors.contract import TurnBudget
from ki_dev.adapter.registry import executor_specs
from ki_dev.flow_ops.implement.machine import IMPLEMENT, Limits
from ki_dev.review_context import ProjectionLimits
from ki_dev.runner.safety import SafetyLimits

ROLES = ("worker", "review")

_TEXT = {"type": "string", "pattern": r"\S"}
_TEXTS = {"type": "array", "items": _TEXT}
_CONTAINER = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"launcher": _TEXT},
}


class RunConfigError(ValueError):
    """Die Laufkonfiguration ist ungültig."""


def check_run_config(config: object, where: str) -> None:
    """Gegen das Schema prüfen; ``where`` benennt die Quelle (Profil,
    Laufkonfiguration) in der Meldung."""
    errors = sorted(
        _validator().iter_errors(config),
        key=lambda e: list(map(str, e.absolute_path)),
    )
    if errors:
        raise RunConfigError(f"{where}: {_describe(errors[0])}")


def _describe(error: ValidationError) -> str:
    """Feldpfad und Regel; Feldnamen ja, Werte nie."""
    path = ".".join(map(str, error.absolute_path)) or "$"
    instance = error.instance
    if not isinstance(instance, dict):
        instance = {}
    if error.validator == "required":
        missing = [
            k for k in error.validator_value if k not in instance
        ]
        return f"{path}: fehlende Felder {missing}"
    if error.validator == "additionalProperties":
        known = error.schema.get("properties", {})
        extra = sorted(set(instance) - set(known))
        return f"{path}: unbekannte Felder {extra}"
    return f"{path}: {error.validator}"


@cache
def _validator() -> Draft202012Validator:
    return Draft202012Validator(run_config_schema(executor_specs()))


def run_config_schema(
    specs: Mapping[str, ExecutorSpec],
) -> dict[str, object]:
    """Schema der Laufkonfiguration zu den deklarierten Executoren."""
    role = _role_schema(specs)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "workdir",
            "access_profile",
            *ROLES,
            "finalization",
        ],
        "properties": {
            "task": _TEXT,
            "acceptance_criteria": {**_TEXTS, "minItems": 1},
            "sources": _TEXTS,
            "workdir": _TEXT,
            "access_profile": {"enum": [item.value for item in Access]},
            "env": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
            **dict.fromkeys(ROLES, role),
            "tests": {"type": "array", "items": _CHECK},
            "limits": _numbers(Limits),
            "projection_limits": _numbers(ProjectionLimits),
            "safety_limits": _numbers(SafetyLimits),
            "finalization": _FINALIZATION,
            "usage_task": _USAGE_TASK,
            "container": _CONTAINER,
        },
    }


def _role_schema(
    specs: Mapping[str, ExecutorSpec],
) -> dict[str, object]:
    """Je Executor ein Zweig: seine Felder folgen aus dem Transport."""
    return {
        "type": "object",
        "required": ["executor"],
        "properties": {"executor": {"enum": sorted(specs)}},
        "allOf": [
            {
                "if": {
                    "required": ["executor"],
                    "properties": {"executor": {"const": name}},
                },
                "then": _role_fields(spec),
            }
            for name, spec in sorted(specs.items())
        ],
    }


def _role_fields(spec: ExecutorSpec) -> dict[str, object]:
    executor = {"executor": {"const": spec.name}}
    if spec.transport in cli_transports():
        return {
            "additionalProperties": False,
            "required": ["model", "effort"],
            "properties": {
                **executor,
                "session_id": _TEXT,
                "model": _TEXT,
                "effort": {"enum": [item.value for item in Effort]},
                "executable": _TEXT,
                "timeout_s": {"type": "number"},
                "budget": _numbers(TurnBudget),
            },
        }
    if spec.transport == mock.NAME:
        return {
            "additionalProperties": False,
            "properties": {
                **executor,
                "answers": {
                    "type": "array",
                    "items": {"enum": list(IMPLEMENT.review_events())},
                },
                "file": _TEXT,
            },
        }
    if spec.transport in (manual.CONSOLE, manual.INBOX):
        return {"additionalProperties": False, "properties": executor}
    raise RunConfigError(
        f"executor.{spec.name}: Transport {spec.transport} ohne "
        "Rollenfelder"
    )


def _numbers(limits: type) -> dict[str, object]:
    """Felder einer Grenzen-Dataclass; der Typ folgt ihrem
    Standardwert (``int`` → integer, ``float`` → number)."""
    properties: dict[str, object] = {}
    for item in fields(limits):
        default = item.default
        if default is MISSING:
            raise TypeError(
                f"{limits.__name__}.{item.name} ohne Standardwert"
            )
        kind = "integer" if type(default) is int else "number"
        properties[item.name] = {"type": kind}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }


_CHECK = {
    "type": "object",
    "additionalProperties": False,
    "required": ["name", "argv"],
    "properties": {
        "name": _TEXT,
        "argv": {**_TEXTS, "minItems": 1},
        "timeout_s": {"type": "number"},
    },
}
_FINALIZATION = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "target_workdir",
        "target_ref",
        "commit_message",
    ],
    "properties": {
        "target_workdir": _TEXT,
        "target_ref": _TEXT,
        "commit_message": _TEXT,
        "data_mode": _TEXT,
    },
}
_USAGE_TASK = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "bead_id",
        "task_revision",
        "family_id",
        "family_revision",
    ],
    "properties": {
        name: {"type": "string"}
        for name in (
            "bead_id",
            "task_revision",
            "family_id",
            "family_revision",
            "parent_bead_id",
        )
    },
}
