"""Eingaben des Menschen in der Folgerunde: Rückmeldung des
Schreibagenten (``--feedback-file``), Review-Antwort
(``--decision-file``) und die Grenze ``feedback_max_chars``.

Die kleinen I/O-Grenzen der Folgerunde: die Grenze aus
``pyproject.toml`` und die ausdrücklich angegebenen Texte (Datei oder
stdin) mit einem gemeinsamen, begrenzten Leser. Das
Rendering der Folgenachricht steht im Ausführer (``runner.turns``,
Bausteine in ``ops.context``), die Ablaufsteuerung in ``step.cli``.
Keine Dateiablage, kein Zustand zwischen Aufrufen, keine
Beads-Notizen.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from ki_dev.adapter.manual import Console
from ki_dev.config_sources import ConfigSource
from ki_dev.ops.checks.preflight import (
    CONFIG_FILE,
    PreflightConfigError,
    read_toml,
)
from ki_dev.ops.context.contract import (
    NONEMPTY_TEXT_SCHEMA,
)

CONFIG_TABLE = "tool.ki-dev.handoff"
CONFIG_KEY = "feedback_max_chars"
DEFAULT_FEEDBACK_MAX_CHARS = 600
CONFIG_SOURCE = ConfigSource(
    "handoff --next-turn", str(CONFIG_FILE), CONFIG_TABLE, CONFIG_FILE
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


class NextTurnInputError(ValueError):
    """Aufruf, Konfiguration oder Rückmeldung ungültig (Exit 2)."""


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
        raise NextTurnInputError(
            f"Konfiguration ungültig: {exc}"
        ) from exc
    try:
        Draft202012Validator(_CONFIG_SCHEMA).validate(document)
    except ValidationError as exc:
        raise NextTurnInputError(
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
        raise NextTurnInputError(
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


def read_feedback(source: str, limit: int, console: Console) -> str:
    """Rückmeldung aus Datei oder stdin (``-``) lesen und prüfen.

    Datei und stdin laufen durch denselben UTF-8-Leser des Adapters,
    der höchstens ``limit + 1`` Zeichen liest und dekodiert. Zeichen
    zählen unverändert (auch Leerraum und Zeilenumbrüche); es wird nie
    gekürzt. ``stdin`` der Konsole ist ein Lieferant, damit ohne diese
    Angabe kein stdin angefasst wird.
    """
    text = console.receive(source, limit, "Rückmeldung")
    _check_feedback(text, limit)
    return text


def _check_feedback(text: str, limit: int) -> None:
    """Leer/Leerraum und Überlänge deklarativ prüfen (Diagnose ohne
    Rohwert)."""
    schema = {**NONEMPTY_TEXT_SCHEMA, "maxLength": limit}
    for error in Draft202012Validator(schema).iter_errors(text):
        if error.validator == "maxLength":
            raise NextTurnInputError(
                f"Rückmeldung überschreitet {limit} Zeichen "
                f"({CONFIG_TABLE}.{CONFIG_KEY}); keine Kürzung, bitte "
                "kürzen"
            )
        raise NextTurnInputError("Rückmeldung ist leer")


# Obergrenze der eingelesenen Review-Antwort (Zeichen); nie gekürzt.
DECISION_MAX_CHARS = 20000
_DECISION_WHAT = "Review-Antwort"


class DecisionInputError(ValueError):
    """Review-Antwort ungültig, zu lang oder am falschen Ort (Exit 2),
    ohne Rohwerte."""


def read_decision(source: str, console: Console) -> str:
    """Review-Antwort aus Datei oder stdin (``-``), begrenzt."""
    text = console.receive(source, DECISION_MAX_CHARS, _DECISION_WHAT)
    if len(text) > DECISION_MAX_CHARS:
        raise DecisionInputError(
            f"{_DECISION_WHAT} überschreitet {DECISION_MAX_CHARS} "
            "Zeichen; keine Kürzung"
        )
    return text
