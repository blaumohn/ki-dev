"""Gemeinsamer Antwortvertrag für Reviews (step und run).

Kern ist ein JSON-Objekt ``{event, detail, requirement_ref}``. ``event``
ist ein Review-Ereignis des Ablaufs: ``PASS`` oder eine seiner
Befundklassen (``finding_class``); das Urteil (CHANGES,
NEEDS_DECISION, ESCALATE) folgt aus der Klasse und steht nie selbst in
der Antwort. So gibt es genau ein Vokabular: das des Ablaufs.

Alle Feldregeln stehen im JSON Schema (Draft202012Validator), auch die
zwei Regeln zwischen den Feldern (``if``/``then``); das erlaubte
``event``-enum entsteht aus dem Ablauf. ``ki-dev -f implement`` legt
eine Identitätshülle (run_id, round_id) um denselben Kern; step hat
keine (kein Laufspeicher) und bindet die Antwort über die
Abnahmekriterien des Beads (AC1..ACn).

Ein Ablauf mit Prüffragen (``Flow.review_questions``) verlangt zwei
weitere Felder: ``answers`` beantwortet jede Frage,
``observations`` nennt Mängel außerhalb der Kriterien. Beide lenken den
Ablauf nicht; sie gehen an den Menschen.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from typing import Protocol, cast

from jsonschema import Draft202012Validator

from ki_dev.flow.model import PASS, Flow, Verdict
from ki_dev.json_reply import unwrap_json_fence

CORE_FIELDS = ("event", "detail", "requirement_ref")


class ReviewContractError(ValueError):
    """Review-Antwort verletzt den Vertrag; nennt Feldpfad, keine
    Rohwerte."""


@dataclass(frozen=True)
class ReviewVerdict:
    """Geprüfter Kern einer Review-Antwort."""

    event: str
    detail: str
    requirement_ref: str | None
    answers: Mapping[str, str] = field(default_factory=dict)
    observations: tuple[str, ...] = ()


def load_json_object(raw: str) -> dict:
    """Genau ein JSON-Objekt, höchstens in einem umschließenden
    Codeblock; Parsing getrennt von der Prüfung. Der Fehler nennt Art
    und Stelle, keine Rohwerte, damit die Wiederholung ihn beheben
    kann."""
    try:
        value = json.loads(unwrap_json_fence(raw))
    except json.JSONDecodeError as exc:
        raise ReviewContractError(
            "Review-Ausgabe ist kein einzelnes JSON-Objekt "
            f"({exc.msg}, Zeile {exc.lineno}, Spalte {exc.colno}); "
            "nur das Objekt, ohne Text davor oder danach"
        ) from exc
    if not isinstance(value, dict):
        raise ReviewContractError(
            "Review-Ausgabe ist kein einzelnes JSON-Objekt"
        )
    return value


def parse_verdict(
    value: Mapping[str, object],
    flow: Flow,
    extra_properties: Mapping[str, dict] | None = None,
) -> ReviewVerdict:
    """Kern gegen das Review-Vokabular von ``flow`` prüfen.
    ``extra_properties`` erlaubt einem Aufrufer zusätzliche, optionale
    Felder mit eigenem Schema (step: 5we)."""
    _check_schema(value, flow, extra_properties or {})
    event = cast(str, value["event"])
    detail = cast(str, value["detail"])
    ref = cast("str | None", value["requirement_ref"])
    return ReviewVerdict(
        event,
        detail,
        ref,
        cast("dict[str, str]", value.get("answers", {})),
        tuple(cast("list[str]", value.get("observations", []))),
    )


class _Bindable(Protocol):
    event: str
    detail: str
    requirement_ref: str | None


def bind_requirement[D: _Bindable](
    decision: D, refs: Collection[str], flow: Flow
) -> D:
    """Binde ein CHANGES-Ereignis an ein bestehendes, eindeutiges
    Abnahmekriterium.

    Eine fehlende, unbekannte oder fremde Referenz wird nicht als
    Reparaturauftrag übernommen: mehrdeutige Anforderungen oder eine
    strengere neue Interpretation brauchen eine menschliche Klärung
    (``flow.unbound_changes_event()``, NEEDS_DECISION) statt einer
    automatischen Runde. Geprüft wird nur die technische Referenz,
    nicht die inhaltliche Berechtigung.
    """
    if flow.verdict(decision.event) is not Verdict.CHANGES:
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
        event=flow.unbound_changes_event(),
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
# Marke am Anfang eines Kriteriums: "[error] ...".
_MARKER = re.compile(r"\A\[([a-z_]+)\]")


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


def criteria_form_problems(
    text: str, markers: Collection[str]
) -> tuple[str, ...]:
    """Form der Abnahmekriterien eines Auftrags (halbformal, bis Beads
    sie selbst prüft): nummeriert, und jede Marke aus ``markers`` trägt
    mindestens ein Kriterium. Inhalte prüft das nicht."""
    if _NUMBERED.search(text) is None:
        return (
            "acceptance_criteria: nicht nummeriert; je Kriterium eine "
            'Zeile "1. ...", auch bei nur einem',
        )
    criteria = split_acceptance_criteria(text)
    found = {
        match.group(1)
        for match in map(_MARKER.match, criteria)
        if match is not None
    }
    return tuple(
        f"acceptance_criteria: kein Kriterium mit [{marker}]; ohne "
        f'solchen Fall ausdrücklich: "[{marker}] entfällt: Grund"'
        for marker in markers
        if marker not in found
    )


# --- Schema und Feldregeln ----------------------------------------

_TEXT_SCHEMA = {"type": "string", "minLength": 1, "pattern": r"\S"}
_REF_SCHEMA = {"anyOf": [{"type": "null"}, _TEXT_SCHEMA]}


def _event_rules(flow: Flow) -> list[dict]:
    """Regeln zwischen Feldern: Nicht-PASS braucht ein nichtleeres
    detail; requirement_ref ist außer bei CHANGES-Ereignissen null."""
    changes = list(flow.events_with(Verdict.CHANGES))
    return [
        {
            "if": {
                "required": ["event"],
                "properties": {"event": {"not": {"const": PASS}}},
            },
            "then": {"properties": {"detail": {"pattern": r"\S"}}},
        },
        {
            "if": {
                "required": ["event"],
                "properties": {"event": {"not": {"enum": changes}}},
            },
            "then": {
                "properties": {"requirement_ref": {"type": "null"}}
            },
        },
    ]


# Diagnose je (Feld, Regel); der Text stammt aus dem Vertrag, nie aus
# der Antwort.
_FIELD_DIAGNOSES = {
    ("detail", "pattern"): "Nicht-PASS braucht eine Begruendung",
    (
        "requirement_ref",
        "type",
    ): "ist außer bei CHANGES-Ereignissen null",
}

_DIAGNOSES = {
    "required": "fehlt",
    "additionalProperties": "unbekanntes Feld",
    "enum": "ungültiger Wert",
    "type": "falscher Typ",
    "anyOf": "muss null oder nichtleerer Text sein",
    "minLength": "muss nichtleerer Text sein",
    "pattern": "muss nichtleerer Text sein",
}


def review_schema(
    flow: Flow, extra: Mapping[str, dict] | None = None
) -> dict:
    """JSON Schema des Kerns; das ``event``-enum und die Prüffragen
    kommen aus ``flow``."""
    findings = _finding_fields(flow)
    return {
        "type": "object",
        "required": [*CORE_FIELDS, *findings],
        "additionalProperties": False,
        "properties": {
            "event": {"enum": list(flow.review_events())},
            "detail": {"type": "string"},
            "requirement_ref": _REF_SCHEMA,
            **findings,
            **(extra or {}),
        },
        "allOf": _event_rules(flow),
    }


def _finding_fields(flow: Flow) -> dict[str, dict]:
    """``answers`` (jede Prüffrage genau einmal) und ``observations``;
    ein Ablauf ohne Prüffragen kennt beide Felder nicht."""
    questions = list(flow.review_questions)
    if not questions:
        return {}
    return {
        "answers": {
            "type": "object",
            "required": questions,
            "additionalProperties": False,
            "properties": dict.fromkeys(questions, _TEXT_SCHEMA),
        },
        "observations": {"type": "array", "items": _TEXT_SCHEMA},
    }


def cli_schema(flow: Flow) -> dict:
    """Das Schema in der Form, die Claude und Codex annehmen: beide
    weisen oberste ``allOf``-Regeln mit HTTP 400 ab (Claude Code
    2.1.316, codex 0.166.0, docs/cli-adapters.md). Die Regeln zwischen
    den Feldern prüft weiter :func:`parse_verdict`."""
    schema = review_schema(flow)
    del schema["allOf"]
    return schema


def _check_schema(
    value: Mapping[str, object],
    flow: Flow,
    extra: Mapping[str, dict],
) -> None:
    validator = Draft202012Validator(review_schema(flow, extra))
    errors = sorted(
        validator.iter_errors(value),
        key=lambda error: list(map(str, error.absolute_path)),
    )
    if errors:
        raise ReviewContractError(_diagnosis(errors[0]))


def _diagnosis(error) -> str:
    """Bereinigte Meldung mit Feldpfad, ohne Rohwerte."""
    path = ".".join(map(str, error.absolute_path))
    prefix = f"{path}." if path else ""
    if error.validator == "required":
        missing = [
            prefix + key
            for key in error.validator_value
            if key not in error.instance
        ]
        return f"{', '.join(missing)}: fehlt"
    if error.validator == "additionalProperties":
        known = set(error.schema.get("properties", {}))
        unknown = sorted(set(error.instance) - known)
        names = ", ".join(prefix + key for key in unknown)
        return f"{names}: unbekanntes Feld"
    message = _FIELD_DIAGNOSES.get(
        (path, str(error.validator)),
        _DIAGNOSES.get(str(error.validator), "ist ungültig"),
    )
    return f"{path or '$'}: {message}"
