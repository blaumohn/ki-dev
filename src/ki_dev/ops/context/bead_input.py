"""Bead-Eingabe der Übergaben: Typ, formale Prüfung je Schritt,
Abnahmekriterien mit Referenz.

Die Prüfung kennt nur Schritt und Prüfgegenstand; Rendering und
Ablauf liegen bei den Aufrufern.
"""

from __future__ import annotations

from dataclasses import dataclass

from jsonschema import Draft202012Validator

from ki_dev.flow.planning import NAME
from ki_dev.flow.templates import render
from ki_dev.ops.context.contract import (
    NONEMPTY_TEXT_SCHEMA,
    ReviewTarget,
    Step,
)
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
_REFS_STEPS = {Step.MAP, Step.GRAPH, Step.MATERIALIZE}
_CONTRACT_STEPS = {Step.IMPLEMENT}
# Ein fehlender review_target bei Step.REVIEW bleibt die bisherige
# Umsetzungs-Review (Rückwärtskompatibilität von --step review ohne
# --review-of).
_REVIEW_TARGET_REFS = {
    ReviewTarget.MAP,
    ReviewTarget.GRAPH,
    ReviewTarget.MATERIALIZE,
}
_REVIEW_TARGET_CONTRACT = {
    None,
    ReviewTarget.MATERIALIZE,
    ReviewTarget.IMPLEMENT,
}


def _needs_refs(step: Step, review_target: ReviewTarget | None) -> bool:
    if step is Step.REVIEW:
        return review_target in _REVIEW_TARGET_REFS
    return step in _REFS_STEPS


def _needs_contract(
    step: Step, review_target: ReviewTarget | None
) -> bool:
    if step is Step.REVIEW:
        return review_target in _REVIEW_TARGET_CONTRACT
    return step in _CONTRACT_STEPS


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

_CONTRACT_PROPERTIES = {
    "acceptance_criteria": NONEMPTY_TEXT_SCHEMA,
    "design": NONEMPTY_TEXT_SCHEMA,
}
_CONTRACT_REQUIRED = ("acceptance_criteria", "design")

_REFS_PROPERTIES = {
    "metadata": {
        "type": "object",
        "required": ["handoff"],
        "properties": {
            "handoff": {
                "type": "object",
                "required": ["source_refs"],
                "properties": {"source_refs": _SOURCE_REFS_SCHEMA},
            },
        },
    },
}
_REFS_REQUIRED = ("metadata",)


def _issue_schema(*, needs_refs: bool, needs_contract: bool) -> dict:
    properties = dict(_BASE_PROPERTIES)
    required = list(_BASE_REQUIRED)
    if needs_contract:
        properties |= _CONTRACT_PROPERTIES
        required += _CONTRACT_REQUIRED
    if needs_refs:
        properties |= _REFS_PROPERTIES
        required += _REFS_REQUIRED
    return {
        "type": "object",
        "required": required,
        "properties": properties,
    }


# Die vier (step, review_target)-Verträge reduzieren sich auf zwei
# Booleans (_needs_refs/_needs_contract); die Varianten werden beim
# Laden einmal zusammengesetzt statt je Aufruf neu gebaut.
_ISSUE_SCHEMAS = {
    (needs_refs, needs_contract): _issue_schema(
        needs_refs=needs_refs, needs_contract=needs_contract
    )
    for needs_refs in (False, True)
    for needs_contract in (False, True)
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
    step: Step,
    review_target: ReviewTarget | None = None,
) -> tuple[str, ...]:
    """Formale Lücken als Feldpfade; leer heißt vollständig.

    ``review_target`` wirkt nur bei ``step is Step.REVIEW``: er wählt,
    welcher Prüfgegenstand (map/graph/materialize/implement) benötigt
    wird. Für andere Schritte wird er ignoriert.
    """
    refs = _needs_refs(step, review_target)
    contract = _needs_contract(step, review_target)
    schema = _ISSUE_SCHEMAS[(refs, contract)]
    validator = Draft202012Validator(schema)
    paths = {
        tuple(error.absolute_path)
        for error in validator.iter_errors(_issue_payload(issue))
    }
    ordered = sorted(paths, key=_path_sort_key)
    problems = tuple(_field_path(path) for path in ordered)
    if not problems and _is_build_review(step, review_target):
        problems = _criterion_problems(issue)
    return problems


def _criterion_problems(issue: BeadInput) -> tuple[str, ...]:
    """AC-Zerlegung der Umsetzungs-Review vor jedem Vorlauf
    prüfen (Erst-Review, --next-turn und --decision-file teilen
    diese Grenze)."""
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


def _is_build_review(
    step: Step, review_target: ReviewTarget | None
) -> bool:
    return step is Step.REVIEW and review_target in (
        None,
        ReviewTarget.IMPLEMENT,
    )


def criterion_line(issue: BeadInput) -> str:
    """Nur die Referenzen; den Text liest der Reviewer im Bead."""
    refs = ", ".join(ref for ref, _ in criteria_with_refs(issue))
    return render(NAME, "criterion-line", refs=refs)


def criteria_with_refs(issue: BeadInput) -> list[tuple[str, str]]:
    """Abnahmekriterien des Beads mit Referenz; ungültige Nummerierung
    ist ein formaler Mangel (Exit 2), kein stiller Ersatz."""
    text = str(issue.acceptance_criteria)
    try:
        criteria = split_acceptance_criteria(text)
    except ReviewContractError as exc:
        raise BeadInputInvalidError((str(exc),)) from exc
    return list(zip(criterion_refs(criteria), criteria, strict=True))
