"""Grenze ``feedback_max_chars`` aus ``pyproject.toml``: so lang darf
die Rückmeldung des Schreibagenten in seiner Antwort sein
(``{"feedback": …}``); die Übergabe danach zitiert sie, nie gekürzt.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from ki_dev.config_sources import ConfigSource
from ki_dev.ops.checks.preflight import (
    CONFIG_FILE,
    PreflightConfigError,
    read_toml,
)

CONFIG_TABLE = "tool.ki-dev.handoff"
CONFIG_KEY = "feedback_max_chars"
DEFAULT_FEEDBACK_MAX_CHARS = 600
CONFIG_SOURCE = ConfigSource(
    "step (Rückmeldung)", str(CONFIG_FILE), CONFIG_TABLE, CONFIG_FILE
)


_TABLE_KEYS = tuple(CONFIG_TABLE.split("."))

_KEY_PATH = (*_TABLE_KEYS, CONFIG_KEY)
_LIMIT_RULE = "muss eine positive ganze Zahl sein"


def _nested_schema(keys: tuple[str, ...]) -> dict:
    """Optionale, verschachtelte Tabellen bis zum Grenzwert; jede
    vorhandene Ebene muss eine Tabelle sein."""
    if not keys:
        return {"type": "integer", "exclusiveMinimum": 0}
    return {
        "type": "object",
        "properties": {keys[0]: _nested_schema(keys[1:])},
    }


_CONFIG_SCHEMA = _nested_schema(_KEY_PATH)


class FeedbackConfigError(ValueError):
    """Grenze der Rückmeldung ungültig konfiguriert (Exit 2)."""


def load_feedback_max_chars(project_root: Path) -> int:
    """Grenze für die Rückmeldung; fehlende Angabe ist der Standard.

    Eine fehlende Datei, Tabelle oder ein fehlender Schlüssel ist keine
    Konfiguration im Sinne eines Fehlers (das Ziel braucht dann keine
    ``pyproject.toml``); ein vorhandener, aber ungültiger Wert, eine
    falsch typisierte Tabelle oder ungültiges TOML wird abgelehnt.
    """
    path = project_root / CONFIG_FILE
    if not path.exists():
        return DEFAULT_FEEDBACK_MAX_CHARS
    try:
        document = read_toml(path)
    except PreflightConfigError as exc:
        raise FeedbackConfigError(
            f"Konfiguration ungültig: {exc}"
        ) from exc
    try:
        Draft202012Validator(_CONFIG_SCHEMA).validate(document)
    except ValidationError as exc:
        raise FeedbackConfigError(
            f"Konfiguration ungültig: {_diagnosis(exc)}"
        ) from exc
    table: object = document
    for key in (*_TABLE_KEYS, CONFIG_KEY):
        if not isinstance(table, dict) or key not in table:
            return DEFAULT_FEEDBACK_MAX_CHARS
        table = table[key]
    # jsonschema lässt 600.0 als integer zu; "ganze Zahl" meint hier
    # den TOML-Typ Integer.
    if isinstance(table, float):
        raise FeedbackConfigError(
            f"Konfiguration ungültig: {_diagnosis_path(_KEY_PATH)} "
            f"{_LIMIT_RULE}"
        )
    return cast(int, table)


def _diagnosis(error: ValidationError) -> str:
    """Feldpfad und feste Regelbeschreibung, nie der Rohwert."""
    path = tuple(str(part) for part in error.absolute_path)
    if path == _KEY_PATH:
        return f"{_diagnosis_path(path)} {_LIMIT_RULE}"
    return f"{_diagnosis_path(path)} muss eine Tabelle sein"


def _diagnosis_path(path: tuple[str, ...]) -> str:
    return ".".join(path)
