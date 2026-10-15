"""Vertrag für Anforderungskatalog und Ergebnisbericht.

Maßgeblich ist ``report.schema.json``; die Aufzählungen hier werden
daraus gelesen, nicht nebenher gepflegt.
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

_SCHEMA = json.loads(
    (Path(__file__).with_name("report.schema.json")).read_text()
)
_DEFS = _SCHEMA["$defs"]

STATUSES = tuple(_DEFS["status"]["enum"])
BLOCK_STAGES = tuple(
    _DEFS["blocked"]["properties"]["stage"]["enum"]
)


def problems(definition: str, data: object) -> list[str]:
    """Verletzungen von ``$defs/<definition>`` mit Feldpfad, ohne
    Rohwerte."""
    validator = Draft202012Validator(
        {"$ref": f"#/$defs/{definition}", **_SCHEMA}
    )
    return sorted(
        f"{_path(error.absolute_path)}: {error.validator} verletzt"
        for error in validator.iter_errors(data)
    )


def _path(parts) -> str:
    return "/".join(map(str, parts)) or "(Wurzel)"
