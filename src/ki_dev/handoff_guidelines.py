"""Leitlinien als Daten: Vertrag, feste Auswahl je Schritt, Rendering.

Reiner Kern ohne Dateizugriff. Lesen und YAML-Parsing liegen in
``handoff_guidelines_source``; dieses Modul erhält bereits geparste
Daten und prüft sie gegen den Vertrag (Draft202012Validator plus
benannte Referenzprüfung).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from jsonschema import Draft202012Validator, ValidationError

from ki_dev.handoff import NONEMPTY_TEXT_SCHEMA, ReviewTarget, Step


@dataclass(frozen=True)
class GuidelineSource:
    """YAML-Quelle und die daraus erzeugte Markdown-Seite."""

    path: PurePosixPath
    document: PurePosixPath


# Feste Reihenfolge: Architektur/Programmierung, Technik, Arbeitsregeln.
GUIDELINE_SOURCES = (
    GuidelineSource(
        PurePosixPath("docs/policies/programmierleitlinie.de.yaml"),
        PurePosixPath("docs/programmierleitlinie.de.md"),
    ),
    GuidelineSource(
        PurePosixPath("docs/policies/technikleitlinie.de.yaml"),
        PurePosixPath("docs/technikleitlinie.de.md"),
    ),
    GuidelineSource(
        PurePosixPath("docs/policies/arbeitsregeln.de.yaml"),
        PurePosixPath("docs/arbeitsregeln.de.md"),
    ),
)

GENERATOR = "scripts/render-guidelines.py"


@dataclass(frozen=True)
class GuidelineSection:
    """Ein ausgewählter Abschnitt samt Quellenkennzeichnung."""

    source: str
    id: str
    text: str


@dataclass(frozen=True)
class GuidelineDocument:
    """Vertragsgemäß geprüfte Leitlinie aus einer YAML-Quelle."""

    source: GuidelineSource
    title: str
    permalink: str
    sections: tuple[tuple[str, str], ...]
    common: tuple[str, ...]
    stages: dict[str, dict[str, tuple[str, ...]]]


class GuidelineContractError(ValueError):
    """Leitlinienquelle verletzt den YAML-Vertrag."""

    def __init__(
        self, source: PurePosixPath, problems: tuple[str, ...]
    ):
        super().__init__("; ".join(problems))
        self.source = source
        self.problems = problems


_STAGES = (Step.MAP, Step.GRAPH, Step.MATERIALIZE, Step.BUILD)

_SINGLE_LINE_SCHEMA = {
    "type": "string",
    "pattern": r"^[^\r\n]*\S[^\r\n]*$",
}
_ID_SCHEMA = {"type": "string", "pattern": r"^[a-z0-9][a-z0-9-]*$"}
_ID_LIST_SCHEMA = {"type": "array", "items": _ID_SCHEMA}
_STAGE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["task", "review"],
    "properties": {"task": _ID_LIST_SCHEMA, "review": _ID_LIST_SCHEMA},
}
_SECTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "text"],
    "properties": {"id": _ID_SCHEMA, "text": NONEMPTY_TEXT_SCHEMA},
}
GUIDELINE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "permalink", "common", "stages", "sections"],
    "properties": {
        "title": _SINGLE_LINE_SCHEMA,
        "permalink": _SINGLE_LINE_SCHEMA,
        "common": _ID_LIST_SCHEMA,
        "stages": {
            "type": "object",
            "additionalProperties": False,
            "required": [stage.value for stage in _STAGES],
            "properties": {
                stage.value: _STAGE_SCHEMA for stage in _STAGES
            },
        },
        "sections": {
            "type": "array",
            "minItems": 1,
            "items": _SECTION_SCHEMA,
        },
    },
}
_VALIDATOR = Draft202012Validator(GUIDELINE_SCHEMA)

_TYPE_NAMES = {"string": "Text", "array": "Liste", "object": "Mapping"}


def parse_guideline_document(
    source: GuidelineSource, data: object
) -> GuidelineDocument:
    """Geparste YAML-Daten prüfen und normalisieren.

    Diagnosen nennen Feldpfade, nie Regeltexte oder ID-Werte.
    """
    problems = sorted(
        {_diagnosis(e) for e in _VALIDATOR.iter_errors(data)}
    )
    if not problems:
        problems = _reference_problems(data)
    if problems:
        raise GuidelineContractError(source.path, tuple(problems))
    return GuidelineDocument(
        source=source,
        title=data["title"],
        permalink=data["permalink"],
        sections=tuple((s["id"], s["text"]) for s in data["sections"]),
        common=tuple(data["common"]),
        stages={
            stage: {kind: tuple(ids) for kind, ids in lists.items()}
            for stage, lists in data["stages"].items()
        },
    )


def _diagnosis(error: ValidationError) -> str:
    return f"{_field_path(error.absolute_path)}: {_reason(error)}"


def _field_path(path) -> str:
    text = ""
    for part in path:
        text += f"[{part}]" if isinstance(part, int) else f".{part}"
    return text.lstrip(".") or "(Wurzel)"


def _reason(error: ValidationError) -> str:
    if error.validator == "type":
        return f"muss {_TYPE_NAMES[error.validator_value]} sein"
    if error.validator == "required":
        missing = [
            name
            for name in error.validator_value
            if name not in error.instance
        ]
        return f"Pflichtfeld {', '.join(missing)} fehlt"
    if error.validator == "additionalProperties":
        return "unbekanntes Feld"
    if error.schema is _ID_SCHEMA:
        return "ungültige Abschnitts-ID (erlaubt: a-z, 0-9, -)"
    if error.schema is _SINGLE_LINE_SCHEMA:
        return "muss nichtleerer einzeiliger Text sein"
    if error.validator in ("minLength", "minItems", "pattern"):
        return "darf nicht leer sein"
    return "ungültig"


def _reference_problems(data: dict) -> list[str]:
    """Benannte Zusatzprüfung: eindeutige IDs, bekannte Referenzen."""
    problems = []
    known = set()
    for index, section in enumerate(data["sections"]):
        if section["id"] in known:
            problems.append(
                f"sections[{index}].id: doppelte Abschnitts-ID"
            )
        known.add(section["id"])
    references = [("common", data["common"])] + [
        (f"stages.{stage}.{kind}", ids)
        for stage, lists in data["stages"].items()
        for kind, ids in lists.items()
    ]
    for path, ids in references:
        problems += [
            f"{path}[{index}]: unbekannte Abschnitts-ID"
            for index, section_id in enumerate(ids)
            if section_id not in known
        ]
    return problems


def select_guidelines(
    documents: tuple[GuidelineDocument, ...],
    step: Step,
    review_target: ReviewTarget | None = None,
) -> tuple[GuidelineSection, ...]:
    """Feste Auswahl: common + task des Ziels, bei Review + review.

    ``Step.REVIEW`` ohne ``review_target`` bleibt die Build-Review.
    Reihenfolge aus ``sections``, je Quelle jede ID einmal.
    """
    target, is_review = _target(step, review_target)
    selected = []
    for document in documents:
        stage = document.stages[target.value]
        wanted = set(document.common) | set(stage["task"])
        if is_review:
            wanted |= set(stage["review"])
        selected += _sections_of(document, wanted)
    return tuple(selected)


def select_common_guidelines(
    documents: tuple[GuidelineDocument, ...],
) -> tuple[GuidelineSection, ...]:
    """Nur ``common`` je Quelle, für Sitzungen ohne Schritt (lokal).
    Reihenfolge und Einmaligkeit wie ``select_guidelines``."""
    selected = []
    for document in documents:
        selected += _sections_of(document, set(document.common))
    return tuple(selected)


def _sections_of(
    document: GuidelineDocument, wanted: set[str]
) -> list[GuidelineSection]:
    return [
        GuidelineSection(str(document.source.path), section_id, text)
        for section_id, text in document.sections
        if section_id in wanted
    ]


def _target(
    step: Step, review_target: ReviewTarget | None
) -> tuple[Step, bool]:
    if step is not Step.REVIEW:
        return step, False
    return Step((review_target or ReviewTarget.BUILD).value), True


def render_guideline_documents(
    documents: tuple[GuidelineDocument, ...],
) -> dict[PurePosixPath, str]:
    """Vollständige Markdown-Seiten je Zielpfad, alle Abschnitte."""
    return {
        document.source.document: _render_document(document)
        for document in documents
    }


def _render_document(document: GuidelineDocument) -> str:
    header = (
        "---\n"
        "layout: page\n"
        f"title: {document.title}\n"
        f"permalink: {document.permalink}\n"
        "---\n"
        f"<!-- Generiert aus {document.source.path} mit {GENERATOR}; "
        "Änderungen dort vornehmen. -->\n"
    )
    body = "\n\n".join(text for _, text in document.sections)
    return f"{header}\n{body}\n"
