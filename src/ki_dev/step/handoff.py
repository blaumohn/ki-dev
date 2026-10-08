"""Reiner Kern für geprüfte Arbeitsübergaben (ki-dev step)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from jsonschema import Draft202012Validator

from ki_dev.flow.planning import NAME, PlanningFlow
from ki_dev.flow.templates import lines as lines_of
from ki_dev.flow.templates import render
from ki_dev.review_decision import (
    ReviewContractError,
    criterion_refs,
    split_acceptance_criteria,
)
from ki_dev.step.contract import (
    NONEMPTY_TEXT_SCHEMA,
    ReviewTarget,
    Step,
    one_line,
)
from ki_dev.step.guidelines import (
    GuidelineSection,
    render_guideline_block,
)
from ki_dev.step.limit import check_base_length


@dataclass(frozen=True)
class HandoffIssue:
    """Normalisierte Bead-Rohwerte; Typen prüft validate_handoff."""

    id: object = None
    title: object = None
    description: object = None
    design: object = None
    acceptance_criteria: object = None
    source_refs: object = None
    epic_context: tuple[tuple[str, str], ...] = ()


class HandoffInvalidError(ValueError):
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
# nichtleerer Texte, unabhängig vom internen HandoffIssue-Feldnamen.
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


def validate_handoff(
    issue: HandoffIssue,
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


def _criterion_problems(issue: HandoffIssue) -> tuple[str, ...]:
    """AC-Zerlegung der Umsetzungs-Review vor jedem Vorlauf
    prüfen (Erst-Review, --next-turn und --decision-file teilen
    diese Grenze)."""
    try:
        split_acceptance_criteria(str(issue.acceptance_criteria))
    except ReviewContractError as exc:
        return (str(exc),)
    return ()


def _issue_payload(issue: HandoffIssue) -> dict:
    """HandoffIssue als Schema-Instanz; nur zur Validierung gebildet."""
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


def render_handoff(
    issue: HandoffIssue,
    step: Step,
    review_target: ReviewTarget | None = None,
    guidelines: Sequence[GuidelineSection] = (),
    base_max_chars: int | None = None,
    *,
    flow: PlanningFlow,
) -> str:
    """Basisübergabe, danach der gesonderte Leitlinienblock; die Grenze
    gilt nur für die Basis (``None``: ungeprüft). ``flow`` ist die an
    der I/O-Grenze geladene Zustandstabelle."""
    base = render_base_handoff(
        issue, step, review_target, flow=flow, max_chars=base_max_chars
    )
    return base + render_guideline_block(guidelines)


def render_base_handoff(
    issue: HandoffIssue,
    step: Step,
    review_target: ReviewTarget | None = None,
    *,
    flow: PlanningFlow,
    reading_hint: str | None = None,
    max_chars: int | None = None,
) -> str:
    """Kopierbarer Klartext ohne Leitlinien; lehnt formal
    unvollständige Beads ab.

    ``reading_hint`` (Sitzungsimport) gehört zur Basis. Mit
    ``max_chars`` wird der gerenderte Text einschließlich Hinweis und
    abschließendem Zeilenumbruch gezählt; Übergröße wird abgelehnt,
    nie gekürzt.
    """
    problems = validate_handoff(issue, step, review_target)
    if problems:
        raise HandoffInvalidError(problems)
    lines = _base_lines(issue, step, review_target, flow)
    text = "\n".join(lines) + "\n"
    if reading_hint is not None:
        text += f"\n{reading_hint}\n"
    if max_chars is not None:
        fields = _variable_fields(
            issue, step, review_target, reading_hint
        )
        check_base_length(text, max_chars, fields)
    return text


def _base_lines(
    issue: HandoffIssue,
    step: Step,
    review_target: ReviewTarget | None,
    flow: PlanningFlow,
) -> list[str]:
    lines = [f"Schritt: {step.value}"]
    if step is Step.REVIEW:
        effective_target = review_target or ReviewTarget.IMPLEMENT
        lines.append(f"Reviewziel: {effective_target.value}")
    lines += [
        f"Bead: {one_line(issue.id)} - {one_line(issue.title)}",
        "",
        *lines_of(NAME, "common"),
        "",
        *_roles(step, review_target, flow),
    ]
    if issue.epic_context:
        lines += ["", *lines_of(NAME, "epic-intro")]
    for epic_id, epic_context in issue.epic_context:
        lines += [
            "",
            render(
                NAME,
                "epic-hint",
                id=one_line(epic_id),
                context=one_line(epic_context),
            ),
        ]
    if _needs_refs(step, review_target):
        lines += ["", "Quellenreferenzen (unaufgelöst):"]
        lines += [f"- {one_line(ref)}" for ref in issue.source_refs]
    if _is_build_review(step, review_target):
        lines += ["", _criterion_line(issue)]
    state = flow_state(step, review_target)
    lines += ["", *flow.hint_lines(state, one_line(issue.id))]
    return lines


def _is_build_review(
    step: Step, review_target: ReviewTarget | None
) -> bool:
    return step is Step.REVIEW and review_target in (
        None,
        ReviewTarget.IMPLEMENT,
    )


def _criterion_line(issue: HandoffIssue) -> str:
    """Nur die Referenzen; den Text liest der Reviewer im Bead."""
    refs = ", ".join(ref for ref, _ in criteria_with_refs(issue))
    return render(NAME, "criterion-line", refs=refs)


def criteria_with_refs(issue: HandoffIssue) -> list[tuple[str, str]]:
    """Abnahmekriterien des Beads mit Referenz; ungültige Nummerierung
    ist ein formaler Mangel (Exit 2), kein stiller Ersatz."""
    text = str(issue.acceptance_criteria)
    try:
        criteria = split_acceptance_criteria(text)
    except ReviewContractError as exc:
        raise HandoffInvalidError((str(exc),)) from exc
    return list(zip(criterion_refs(criteria), criteria, strict=True))


def flow_state(step: Step, review_target: ReviewTarget | None) -> str:
    """Zustand der Tabelle flow/planning.toml, in dem diese Übergabe
    entsteht (Schreibschritt oder Review der jeweiligen Phase)."""
    if step is Step.REVIEW:
        return (
            f"{(review_target or ReviewTarget.IMPLEMENT).value}.review"
        )
    return step.value


def ensure_base_fits(
    issue: HandoffIssue,
    step: Step,
    review_target: ReviewTarget | None,
    max_chars: int,
    *,
    flow: PlanningFlow,
) -> None:
    """Basisgrenze prüfen, ohne den Text zu verwenden (vor einem
    Vorlauf, der Dateien ändern kann)."""
    render_base_handoff(
        issue, step, review_target, flow=flow, max_chars=max_chars
    )


def _variable_fields(
    issue: HandoffIssue,
    step: Step,
    review_target: ReviewTarget | None,
    reading_hint: str | None,
) -> list[tuple[str, int]]:
    """Zeichenanteile der veränderlichen Basisteile, ohne Rohwerte."""
    fields = [
        ("id", len(one_line(issue.id))),
        ("title", len(one_line(issue.title))),
    ]
    for index, (epic_id, context) in enumerate(issue.epic_context):
        size = len(one_line(epic_id)) + len(one_line(context))
        fields.append((f"epic_context[{index}]", size))
    if _needs_refs(step, review_target):
        for index, ref in enumerate(issue.source_refs):
            fields.append((f"source_refs[{index}]", len(one_line(ref))))
    if _is_build_review(step, review_target):
        size = len(_criterion_line(issue))
        fields.append(("acceptance_criteria", size))
    if reading_hint is not None:
        fields.append(("Lesehinweis", len(reading_hint)))
    return fields


def _roles(
    step: Step, review_target: ReviewTarget | None, flow: PlanningFlow
) -> tuple[str, ...]:
    if step is not Step.REVIEW:
        return lines_of(NAME, f"role-{step.value}")
    target = review_target or ReviewTarget.IMPLEMENT
    return (
        *lines_of(NAME, f"review-{target.value}"),
        *flow.class_lines(),
    )
