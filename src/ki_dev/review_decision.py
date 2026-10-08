"""Gemeinsamer Antwortvertrag für Build-Reviews (step und run).

Kern ist ein JSON-Objekt ``{action, detail, requirement_ref}``. Alle
Feldregeln stehen im JSON Schema (Draft202012Validator), auch die zwei
Regeln zwischen den Feldern (``if``/``then``). ``ki-dev run``
legt eine Identitätshülle (run_id, round_id) um denselben Kern; step
hat keine (kein Laufspeicher) und bindet die Antwort über die
Abnahmekriterien des Beads (AC1..ACn).

Erlaubte Aktionen sind ein Parameter: step kennt PASS, CHANGES und
NEEDS_DECISION; ``ki-dev run`` zusätzlich ESCALATE.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol, cast

from jsonschema import Draft202012Validator


class ReviewAction(StrEnum):
    CHANGES = "CHANGES"
    PASS = "PASS"
    NEEDS_DECISION = "NEEDS_DECISION"
    ESCALATE = "ESCALATE"


STEP_ACTIONS = (
    ReviewAction.PASS,
    ReviewAction.CHANGES,
    ReviewAction.NEEDS_DECISION,
)
RUN_ACTIONS = (*STEP_ACTIONS, ReviewAction.ESCALATE)
CORE_FIELDS = ("action", "detail", "requirement_ref")


class ReviewContractError(ValueError):
    """Review-Antwort verletzt den Vertrag; nennt Feldpfad, keine
    Rohwerte."""


@dataclass(frozen=True)
class ReviewVerdict:
    """Geprüfter Kern einer Review-Antwort."""

    action: ReviewAction
    detail: str
    requirement_ref: str | None


def load_json_object(raw: str) -> dict:
    """Genau ein JSON-Objekt; Parsing getrennt von der Prüfung."""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReviewContractError(
            "Review-Ausgabe ist kein einzelnes JSON-Objekt"
        ) from exc
    if not isinstance(value, dict):
        raise ReviewContractError(
            "Review-Ausgabe ist kein einzelnes JSON-Objekt"
        )
    return value


def parse_verdict(
    value: Mapping[str, object],
    actions: Collection[ReviewAction],
    extra_properties: Mapping[str, dict] | None = None,
) -> ReviewVerdict:
    """Kern prüfen. ``extra_properties`` erlaubt einem Aufrufer
    zusätzliche, optionale Felder mit eigenem Schema (step: 5we)."""
    _check_schema(value, actions, extra_properties or {})
    action = ReviewAction(value["action"])
    detail = cast(str, value["detail"])
    ref = cast("str | None", value["requirement_ref"])
    return ReviewVerdict(action, detail, ref)


class _Bindable(Protocol):
    action: ReviewAction
    detail: str
    requirement_ref: str | None


def bind_requirement[D: _Bindable](
    decision: D, refs: Collection[str]
) -> D:
    """Binde CHANGES an ein bestehendes, eindeutiges Abnahmekriterium.

    Eine fehlende, unbekannte oder fremde Referenz wird nicht als
    Reparaturauftrag übernommen: mehrdeutige Anforderungen oder eine
    strengere neue Interpretation brauchen eine menschliche Klärung
    (NEEDS_DECISION) statt einer automatischen Baurunde. Geprüft wird
    nur die technische Referenz, nicht die inhaltliche Berechtigung.
    """
    if decision.action is not ReviewAction.CHANGES:
        return decision
    if decision.requirement_ref in refs:
        return decision
    reason = (
        "keine Referenz auf ein bestehendes Abnahmekriterium"
        if not decision.requirement_ref
        else f"unbekanntes oder fremdes Abnahmekriterium "
        f"{decision.requirement_ref!r}"
    )
    return replace(
        decision,
        action=ReviewAction.NEEDS_DECISION,
        detail=(
            f"CHANGES abgewiesen ({reason}); Klaerung noetig statt "
            f"automatischer Baurunde. Ursprungsbegruendung: "
            f"{decision.detail}"
        ),
        requirement_ref=None,
    )


# Abnahmekriterien eines Beads: Zeilen "N. ..." am Zeilenanfang,
# fortlaufend ab 1. Ohne Nummerierung ist das ganze Feld ein Kriterium.
_NUMBERED = re.compile(r"^(\d+)\.\s", re.MULTILINE)


def split_acceptance_criteria(text: str) -> tuple[str, ...]:
    """Bead-Feld acceptance_criteria in AC1..ACn zerlegen.

    Lücken oder Doppel in der Nummerierung sind ein sichtbarer Fehler,
    kein stiller Ersatz durch ein einziges Kriterium.
    """
    matches = list(_NUMBERED.finditer(text))
    if not matches:
        return (text.strip(),)
    numbers = [int(match.group(1)) for match in matches]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ReviewContractError(
            "acceptance_criteria: Nummerierung muss fortlaufend bei 1 "
            "beginnen"
        )
    ends = [match.start() for match in matches[1:]] + [len(text)]
    return tuple(
        text[match.end() : end].strip()
        for match, end in zip(matches, ends, strict=True)
    )


def criterion_refs(criteria: Collection[str]) -> tuple[str, ...]:
    return tuple(f"AC{index}" for index in range(1, len(criteria) + 1))


# --- Schema und Feldregeln ----------------------------------------

_REF_SCHEMA = {
    "anyOf": [
        {"type": "null"},
        {"type": "string", "minLength": 1, "pattern": r"\S"},
    ]
}

# Regeln zwischen Feldern: Nicht-PASS braucht ein nichtleeres detail;
# requirement_ref ist außer bei CHANGES null.
_ACTION_RULES = [
    {
        "if": {
            "required": ["action"],
            "properties": {"action": {"not": {"const": "PASS"}}},
        },
        "then": {"properties": {"detail": {"pattern": r"\S"}}},
    },
    {
        "if": {
            "required": ["action"],
            "properties": {"action": {"not": {"const": "CHANGES"}}},
        },
        "then": {"properties": {"requirement_ref": {"type": "null"}}},
    },
]

# Diagnose je (Feld, Regel); der Text stammt aus dem Vertrag, nie aus
# der Antwort.
_FIELD_DIAGNOSES = {
    ("detail", "pattern"): "Nicht-PASS braucht eine Begruendung",
    ("requirement_ref", "type"): "ist außer bei CHANGES null",
}

_DIAGNOSES = {
    "required": "fehlt",
    "additionalProperties": "unbekanntes Feld",
    "enum": "ungültiger Wert",
    "type": "falscher Typ",
    "anyOf": "muss null oder nichtleerer Text sein",
}


def _schema(
    actions: Collection[ReviewAction], extra: Mapping[str, dict]
) -> dict:
    return {
        "type": "object",
        "required": list(CORE_FIELDS),
        "additionalProperties": False,
        "properties": {
            "action": {"enum": [action.value for action in actions]},
            "detail": {"type": "string"},
            "requirement_ref": _REF_SCHEMA,
            **extra,
        },
        "allOf": _ACTION_RULES,
    }


def _check_schema(
    value: Mapping[str, object],
    actions: Collection[ReviewAction],
    extra: Mapping[str, dict],
) -> None:
    validator = Draft202012Validator(_schema(actions, extra))
    errors = sorted(
        validator.iter_errors(value),
        key=lambda error: list(map(str, error.absolute_path)),
    )
    if errors:
        raise ReviewContractError(_diagnosis(errors[0]))


def _diagnosis(error) -> str:
    """Bereinigte Meldung mit Feldpfad, ohne Rohwerte."""
    path = ".".join(map(str, error.absolute_path))
    if error.validator == "required":
        missing = [
            key
            for key in error.validator_value
            if key not in error.instance
        ]
        return f"{', '.join(missing)}: fehlt"
    if error.validator == "additionalProperties":
        known = set(error.schema.get("properties", {}))
        unknown = sorted(set(error.instance) - known)
        return f"{', '.join(unknown)}: unbekanntes Feld"
    message = _FIELD_DIAGNOSES.get(
        (path, str(error.validator)),
        _DIAGNOSES.get(str(error.validator), "ist ungültig"),
    )
    return f"{path or '$'}: {message}"
