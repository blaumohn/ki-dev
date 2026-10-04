"""Vertrag der Hook-Nutzlast: Ereignis und Issue-JSON aus bd.

Geprüft werden nur die Felder, die das Journal braucht; weitere Felder
der bd-Nutzlast sind erlaubt und landen unverändert in issues/<ID>.json.
Die ID wird Dateiname, deshalb schließt ihr Muster Pfadtrenner und
Leerraum aus.
"""

from __future__ import annotations

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import best_match

from ki_dev.beads_journal.timestamps import timestamp

_FORMATS = FormatChecker()


@_FORMATS.checks("journal-timestamp", raises=ValueError)
def _valid_timestamp(value: object) -> bool:
    if isinstance(value, str):
        timestamp(value)
    return True


EVENTS = ("create", "update", "close")
ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]*-[A-Za-z0-9]+(\.[0-9]+)*\Z"
_TEXT = {"type": "string", "pattern": r"\S"}
_ID = {"type": "string", "pattern": ID_PATTERN}
_ISSUE = {
    "type": "object",
    "properties": {
        "id": _ID,
        "title": _TEXT,
        "status": _TEXT,
        # RFC 3339 wie Go time.Time; Bruchteile beliebig lang.
        "updated_at": {
            "type": "string",
            "format": "journal-timestamp",
        },
    },
    "required": ["id", "title", "status", "updated_at"],
}
_EVENT_VALIDATOR = Draft202012Validator(
    {
        "type": "object",
        "properties": {
            "event": {"enum": list(EVENTS)},
            "issue": _ISSUE,
        },
        "required": ["event", "issue"],
    },
    format_checker=_FORMATS,
)
_ISSUE_VALIDATOR = Draft202012Validator(_ISSUE, format_checker=_FORMATS)
_ID_VALIDATOR = Draft202012Validator(_ID)
_REASONS = {
    "required": "Pflichtfeld fehlt",
    "type": "falscher Typ",
    "enum": "unbekannter Wert",
    "pattern": "ungültiges Format",
    "format": "ungültiges Format",
}


class PayloadError(ValueError):
    """Ungültige Nutzlast; Meldung mit Feldpfad, ohne Werte."""


def check_event(event: str, hook_id: str, issue: object) -> None:
    """Prüft Ereignis, Issue-Felder und die ID gegen die Hook-ID."""
    _raise_first(_EVENT_VALIDATOR, {"event": event, "issue": issue}, [])
    if issue["id"] != hook_id:
        raise PayloadError("issue.id: passt nicht zur Hook-ID")


def check_issue(issue: object, prefix: list[str]) -> None:
    """Prüft ein einzelnes Issue, etwa eine Zeile aus bd export."""
    _raise_first(_ISSUE_VALIDATOR, issue, prefix)


def is_issue_id(value: str) -> bool:
    return _ID_VALIDATOR.is_valid(value)


def _raise_first(
    validator: Draft202012Validator, instance: object, prefix: list[str]
) -> None:
    error = best_match(validator.iter_errors(instance))
    if error is None:
        return
    parts = [*prefix, *map(str, error.absolute_path)]
    if error.validator == "required":
        missing = [
            key
            for key in error.validator_value
            if key not in error.instance
        ]
        parts.append(missing[0])
    path = ".".join(parts) or "Nutzlast"
    raise PayloadError(f"{path}: {_REASONS[error.validator]}")
