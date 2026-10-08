"""Konfigurationsgrenze der Basisgrenze (``base_max_chars``).

Liest ``[tool.ki-dev.handoff] base_max_chars`` aus ``pyproject.toml``
und prüft den Vertrag deklarativ (``Draft202012Validator``, auch für
Dictionaries im Speicher). Eigener Leser statt ``read_toml`` aus
``handoff_preflight``: dessen Fehlervertrag unterscheidet Lese- und
Inhaltsfehler nicht, hier ist ein Lesefehler Exit 1, ein Inhaltsfehler
Exit 2.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from ki_dev.config_sources import ConfigSource
from ki_dev.step.limit import (
    CONFIG_KEY,
    CONFIG_TABLE,
    DEFAULT_BASE_MAX_CHARS,
)

CONFIG_FILE = Path("pyproject.toml")
CONFIG_SOURCE = ConfigSource(
    "handoff (Basisgrenze)", str(CONFIG_FILE), CONFIG_TABLE, CONFIG_FILE
)

_KEY_PATH = (*CONFIG_TABLE.split("."), CONFIG_KEY)
_LIMIT_RULE = "muss eine positive ganze Zahl sein"


class LimitConfigInvalidError(ValueError):
    """Konfiguration vorhanden, aber ungültig (Exit 2)."""


class LimitConfigReadError(RuntimeError):
    """Konfigurationsdatei vorhanden, aber nicht lesbar (Exit 1)."""


def _nested_schema(keys: tuple[str, ...]) -> dict:
    """Optionale Tabellen bis zum Grenzwert; jede vorhandene Ebene muss
    eine Tabelle sein, der Wert eine positive Zahl."""
    if not keys:
        return {"type": "integer", "exclusiveMinimum": 0}
    return {
        "type": "object",
        "properties": {keys[0]: _nested_schema(keys[1:])},
    }


_CONFIG_SCHEMA = _nested_schema(_KEY_PATH)


def load_base_max_chars(project_root: Path) -> int:
    """Grenze der Basisübergabe; fehlende Datei oder Angabe ist der
    Standard, ein vorhandener ungültiger Wert nie."""
    path = project_root / CONFIG_FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return DEFAULT_BASE_MAX_CHARS
    except OSError as exc:
        raise LimitConfigReadError(
            f"{CONFIG_FILE} nicht lesbar: {exc.strerror or 'Fehler'}"
        ) from exc
    except UnicodeDecodeError as exc:
        raise LimitConfigInvalidError(
            f"Konfiguration ungültig: {CONFIG_FILE} ist nicht als "
            "UTF-8 lesbar"
        ) from exc
    return base_max_chars_from(_parse(text))


def _parse(text: str) -> dict:
    """Feste Meldung: ``TOMLDecodeError`` kann rohe Schlüsselnamen
    enthalten und wird deshalb nicht übernommen."""
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise LimitConfigInvalidError(
            f"Konfiguration ungültig: {CONFIG_FILE} ist kein gültiges "
            "TOML"
        ) from exc


def base_max_chars_from(document: object) -> int:
    """Grenze aus einem bereits geparsten Dokument; rein."""
    try:
        Draft202012Validator(_CONFIG_SCHEMA).validate(document)
    except ValidationError as exc:
        raise LimitConfigInvalidError(
            f"Konfiguration ungültig: {_diagnosis(exc)}"
        ) from exc
    value: object = document
    for key in _KEY_PATH:
        if not isinstance(value, dict) or key not in value:
            return DEFAULT_BASE_MAX_CHARS
        value = value[key]
    # jsonschema lässt 4000.0 als integer zu; gemeint ist der TOML-Typ.
    if isinstance(value, float):
        raise LimitConfigInvalidError(
            f"Konfiguration ungültig: {'.'.join(_KEY_PATH)} "
            f"{_LIMIT_RULE}"
        )
    return cast(int, value)


def _diagnosis(error: ValidationError) -> str:
    """Feldpfad und feste Regelbeschreibung, nie der Rohwert."""
    path = tuple(str(part) for part in error.absolute_path)
    if path == _KEY_PATH:
        return f"{'.'.join(path)} {_LIMIT_RULE}"
    if not path:
        return "Dokument muss eine Tabelle sein"
    return f"{'.'.join(path)} muss eine Tabelle sein"
