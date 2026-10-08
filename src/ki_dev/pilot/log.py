"""Unveraenderliches Kontrollprotokoll fuer den Agenten-/Reviewablauf
(urq.5).

Haelt Entwuerfe, Reviewbefunde, Korrekturen, Paarurteile, Ablehnungen,
"unklar"-Faelle, Lokalisierungshinweise und den gesonderten
Anteilslisten-Review als eindeutig unterscheidbare Eintraege fest
(docs/architecture/planning-verarbeitungsvertrag.de.md: "Ersturteile
und korrigierte Urteile werden nicht als unabhaengige Beobachtungen
vermischt"). Aehnlichkeitswerte aus search.py erscheinen
ausschliesslich hier, nie als Kantengewicht im Planungsgraphen
(planning.py).

Das Protokoll ist eine reine JSONL-Anhangdatei: jede Zeile ist ein
validierter, unveraenderlicher Eintrag; vorhandene Zeilen werden nie
umgeschrieben oder geloescht.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from ki_dev.planning import PlanningError

_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.@/-]*$")
_ID = {"type": "string", "pattern": _ID_PATTERN.pattern}
_NULLABLE_ID = {"anyOf": [_ID, {"type": "null"}]}


def _object(
    properties: dict, required: list[str] | None = None,
) -> dict:
    return {
        "type": "object", "properties": properties,
        "required": (
            list(properties) if required is None else required
        ),
        "additionalProperties": False,
    }


_SELECTION = {"enum": ["top_k", "sample", "manual"]}
_RANK = {
    "anyOf": [{"type": "integer", "minimum": 1}, {"type": "null"}],
}

_SCHEMAS: dict[str, dict] = {
    "draft": _object({
        "kind": {"const": "draft"}, "id": _ID, "passage_id": _ID,
        "part_id": _ID, "text": {"type": "string", "minLength": 1},
        "assignment": _NULLABLE_ID,
        "operation": {"type": "string", "minLength": 1},
    }),
    "finding": _object({
        "kind": {"const": "finding"}, "id": _ID, "draft_id": _ID,
        "verdict": {"enum": ["confirmed", "rejected", "unclear"]},
        "notes": {"type": "string"},
    }),
    "correction": _object({
        "kind": {"const": "correction"}, "id": _ID,
        "supersedes": _ID, "part_id": _ID,
        "assignment": _NULLABLE_ID,
        "operation": {"type": "string", "minLength": 1},
        "notes": {"type": "string"},
    }),
    "pair_judgment": _object({
        "kind": {"const": "pair_judgment"}, "id": _ID,
        "part_id": _ID, "candidate_id": _ID,
        "candidate_revision": _NULLABLE_ID,
        "verdict": {"enum": ["match", "no_match", "unclear"]},
        "selection": _SELECTION, "rank": _RANK,
        "raw_score": {"type": "number"},
        "model_id": {"type": "string"}, "blind": {"type": "boolean"},
    }),
    "rejection": _object({
        "kind": {"const": "rejection"}, "id": _ID, "part_id": _ID,
        "candidate_id": _NULLABLE_ID,
        "reason": {"type": "string", "minLength": 1},
    }),
    "unclear": _object({
        "kind": {"const": "unclear"}, "id": _ID, "part_id": _ID,
        "candidate_id": _NULLABLE_ID,
        "reason": {"type": "string", "minLength": 1},
    }),
    "localization_warning": _object({
        "kind": {"const": "localization_warning"}, "id": _ID,
        "part_id": _ID,
        "location": {"type": "string", "minLength": 1},
        "same_location_best": {"type": "number"},
        "other_location_best": {"type": "number"},
    }),
    "share_list_review": _object({
        "kind": {"const": "share_list_review"}, "id": _ID,
        "passage_id": _ID,
        "part_ids": {
            "type": "array", "items": _ID, "minItems": 1,
        },
        "complete": {"type": "boolean"}, "notes": {"type": "string"},
    }),
    "search_record": _object({
        "kind": {"const": "search_record"}, "id": _ID,
        "part_id": _ID, "candidate_id": _ID,
        "candidate_revision": _NULLABLE_ID,
        "raw_score": {"type": "number"}, "rank": _RANK,
        "selection": _SELECTION, "model_id": {"type": "string"},
        "visible_in_review": {"type": "boolean"},
    }),
}

KINDS = tuple(_SCHEMAS)


def validate(record: dict) -> dict:
    kind = record.get("kind")
    schema = _SCHEMAS.get(kind)
    if schema is None:
        raise PlanningError(f"unknown control log kind: {kind!r}")
    try:
        Draft202012Validator(schema).validate(record)
    except ValidationError as exc:
        raise PlanningError(f"{kind}: {exc.message}") from exc
    return record


def append(path: Path, record: dict) -> dict:
    """Einen validierten Eintrag ans Kontrollprotokoll anhaengen.

    Nutzt ausschliesslich Anhaengen (`a`-Modus); bestehende Zeilen
    werden nie gelesen, geaendert oder ueberschrieben.
    """
    validate(record)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line + "\n")
    return record


def read_all(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def by_kind(records: list[dict], kind: str) -> list[dict]:
    if kind not in KINDS:
        raise PlanningError(f"unknown control log kind: {kind!r}")
    return [record for record in records if record["kind"] == kind]


def draft(
    *, id: str, passage_id: str, part_id: str, text: str,
    assignment: str | None, operation: str,
) -> dict:
    return validate({
        "kind": "draft", "id": id, "passage_id": passage_id,
        "part_id": part_id, "text": text, "assignment": assignment,
        "operation": operation,
    })


def finding(
    *, id: str, draft_id: str, verdict: str, notes: str = "",
) -> dict:
    return validate({
        "kind": "finding", "id": id, "draft_id": draft_id,
        "verdict": verdict, "notes": notes,
    })


def correction(
    *, id: str, supersedes: str, part_id: str,
    assignment: str | None, operation: str, notes: str = "",
) -> dict:
    return validate({
        "kind": "correction", "id": id, "supersedes": supersedes,
        "part_id": part_id, "assignment": assignment,
        "operation": operation, "notes": notes,
    })


def pair_judgment(
    *, id: str, part_id: str, candidate: Any, verdict: str,
) -> dict:
    return validate({
        "kind": "pair_judgment", "id": id, "part_id": part_id,
        "candidate_id": candidate.unit_id,
        "candidate_revision": candidate.revision,
        "verdict": verdict, "selection": candidate.selection,
        "rank": candidate.rank, "raw_score": candidate.raw_score,
        "model_id": candidate.model_id,
        "blind": not candidate.visible_in_review,
    })


def rejection(
    *, id: str, part_id: str, candidate_id: str | None, reason: str,
) -> dict:
    return validate({
        "kind": "rejection", "id": id, "part_id": part_id,
        "candidate_id": candidate_id, "reason": reason,
    })


def unclear(
    *, id: str, part_id: str, candidate_id: str | None, reason: str,
) -> dict:
    return validate({
        "kind": "unclear", "id": id, "part_id": part_id,
        "candidate_id": candidate_id, "reason": reason,
    })


def localization_warning(
    *, id: str, part_id: str, warning: dict,
) -> dict:
    return validate({
        "kind": "localization_warning", "id": id, "part_id": part_id,
        "location": warning["location"],
        "same_location_best": warning["same_location_best"],
        "other_location_best": warning["other_location_best"],
    })


def share_list_review(
    *, id: str, passage_id: str, part_ids: list[str], complete: bool,
    notes: str = "",
) -> dict:
    return validate({
        "kind": "share_list_review", "id": id,
        "passage_id": passage_id, "part_ids": list(part_ids),
        "complete": complete, "notes": notes,
    })


def search_record(*, id: str, part_id: str, candidate: Any) -> dict:
    return validate({
        "kind": "search_record", "id": id, "part_id": part_id,
        "candidate_id": candidate.unit_id,
        "candidate_revision": candidate.revision,
        "raw_score": candidate.raw_score, "rank": candidate.rank,
        "selection": candidate.selection,
        "model_id": candidate.model_id,
        "visible_in_review": candidate.visible_in_review,
    })
