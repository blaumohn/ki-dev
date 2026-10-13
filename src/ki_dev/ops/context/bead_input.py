"""Bead-Eingabe der Übergaben: Typ, formale Prüfung, Abnahmekriterien
mit Referenz.

Welche Felder eine Übergabe braucht, sagt der Ablauf (``require`` am
Zustand); die Prüfung kennt keine Phase. Rendering und Ablauf liegen
bei den Aufrufern.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache

from jsonschema import Draft202012Validator

from ki_dev.flow.templates import render
from ki_dev.ops.context.contract import NONEMPTY_TEXT_SCHEMA, TEXTS
from ki_dev.review_decision import (
    ReviewContractError,
    criterion_refs,
    split_acceptance_criteria,
)


@dataclass(frozen=True)
class BeadInput:
    """Normalisierte Bead-Rohwerte; Typen prüft validate_bead_input."""

    id: object = None
    title: object = None
    description: object = None
    design: object = None
    acceptance_criteria: object = None
    source_refs: object = None
    epic_context: tuple[tuple[str, str], ...] = ()


class BeadInputInvalidError(ValueError):
    """Bead erfüllt die formalen Pflichtfelder des Schritts nicht."""

    def __init__(self, problems: tuple[str, ...]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


_SOURCE_REFS_PATH = "metadata.handoff.source_refs"


# Gemeinsame Schema-Bausteine (Technikleitlinie: Draft202012Validator,
# einmal je Regel definiert und wiederverwendet). metadata/handoff
# bleiben rein deklarativ: source_refs ist eine nichtleere Liste
# nichtleerer Texte, unabhängig vom internen BeadInput-Feldnamen.
_SOURCE_REFS_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "items": NONEMPTY_TEXT_SCHEMA,
}

_BASE_PROPERTIES = {
    "id": NONEMPTY_TEXT_SCHEMA,
    "title": NONEMPTY_TEXT_SCHEMA,
    "description": NONEMPTY_TEXT_SCHEMA,
}
_BASE_REQUIRED = ("id", "title", "description")

_REFS_SCHEMA = {
    "type": "object",
    "required": ["handoff"],
    "properties": {
        "handoff": {
            "type": "object",
            "required": ["source_refs"],
            "properties": {"source_refs": _SOURCE_REFS_SCHEMA},
        },
    },
}
# Bead-Felder, die ein Ablauf je Übergabe verlangen kann
# (``require`` am Zustand) und ihr Schema in der Bead-Eingabe.
REQUIRABLE = {
    "source_refs": ("metadata", _REFS_SCHEMA),
    "design": ("design", NONEMPTY_TEXT_SCHEMA),
    "acceptance_criteria": (
        "acceptance_criteria",
        NONEMPTY_TEXT_SCHEMA,
    ),
}


@cache
def _issue_schema(require: frozenset[str]) -> dict:
    properties = dict(_BASE_PROPERTIES)
    required = list(_BASE_REQUIRED)
    for name in sorted(require):
        field, schema = REQUIRABLE[name]
        properties[field] = schema
        required.append(field)
    return {
        "type": "object",
        "required": required,
        "properties": properties,
    }


# Reihenfolge der Feldpfade in der Ausgabe, unabhängig von der
# (undefinierten) Reihenfolge, in der Draft202012Validator Fehler über
# mehrere properties hinweg liefert. Geschlüsselt über das erste
# Pfadsegment der rohen jsonschema-Fehlerpfade (vor dem Formatieren).
_FIELD_RANK = {
    "id": 0,
    "title": 1,
    "description": 2,
    "metadata": 3,
    "acceptance_criteria": 4,
    "design": 5,
}


def validate_bead_input(
    issue: BeadInput,
    require: Iterable[str] = (),
    *,
    criteria: bool = False,
) -> tuple[str, ...]:
    """Formale Lücken als Feldpfade; leer heißt vollständig.

    ``require`` nennt die Bead-Felder, die der Ablauf für diese
    Übergabe verlangt (:data:`REQUIRABLE`); ``criteria`` prüft
    zusätzlich die Zerlegung der Abnahmekriterien (Übergabe mit dem
    Baustein ``criteria``)."""
    unknown = sorted(set(require) - set(REQUIRABLE))
    if unknown:
        raise ValueError(f"require: unbekannt {', '.join(unknown)}")
    validator = Draft202012Validator(_issue_schema(frozenset(require)))
    paths = {
        tuple(error.absolute_path)
        for error in validator.iter_errors(_issue_payload(issue))
    }
    ordered = sorted(paths, key=_path_sort_key)
    problems = tuple(_field_path(path) for path in ordered)
    if not problems and criteria:
        problems = _criterion_problems(issue)
    return problems


def _criterion_problems(issue: BeadInput) -> tuple[str, ...]:
    """AC-Zerlegung der Umsetzungs-Review vor jedem Vorlauf
    prüfen (Übergabe und Antwort des Reviews teilen diese
    Grenze)."""
    try:
        split_acceptance_criteria(str(issue.acceptance_criteria))
    except ReviewContractError as exc:
        return (str(exc),)
    return ()


def _issue_payload(issue: BeadInput) -> dict:
    """BeadInput als Schema-Instanz; nur zur Validierung gebildet."""
    return {
        "id": issue.id,
        "title": issue.title,
        "description": issue.description,
        "acceptance_criteria": issue.acceptance_criteria,
        "design": issue.design,
        "metadata": {"handoff": {"source_refs": issue.source_refs}},
    }


def _path_sort_key(path: tuple) -> tuple[int, int]:
    """Sortiert die rohen jsonschema-Pfade vor dem Formatieren:
    zuerst nach Feld (Reihenfolge wie im bisherigen Vertrag), innerhalb
    von source_refs zusätzlich nach Listenindex."""
    index = path[3] if len(path) > 3 else -1
    return (_FIELD_RANK[path[0]], index)


def _field_path(path: tuple) -> str:
    """jsonschema-Fehlerpfad in den bisherigen Feldpfad übersetzen."""
    if path[:3] == ("metadata", "handoff", "source_refs"):
        if len(path) == 3:
            return _SOURCE_REFS_PATH
        return f"{_SOURCE_REFS_PATH}[{path[3]}]"
    return str(path[0])


def criterion_line(issue: BeadInput) -> str:
    """Nur die Referenzen; den Text liest der Reviewer im Bead."""
    refs = ", ".join(ref for ref, _ in criteria_with_refs(issue))
    return render(TEXTS, "criterion-line", refs=refs)


def criteria_with_refs(issue: BeadInput) -> list[tuple[str, str]]:
    """Abnahmekriterien des Beads mit Referenz; ungültige Nummerierung
    ist ein formaler Mangel (Exit 2), kein stiller Ersatz."""
    text = str(issue.acceptance_criteria)
    try:
        criteria = split_acceptance_criteria(text)
    except ReviewContractError as exc:
        raise BeadInputInvalidError((str(exc),)) from exc
    return list(zip(criterion_refs(criteria), criteria, strict=True))
