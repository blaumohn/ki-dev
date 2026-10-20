"""Ergebnisse eines make-readme-check-Laufs als Statuszeile und Ausgabe.

tests/readme/lib.sh schreibt je README-Skript DIR/<Name ohne .sh>.json:
eine JSON-Liste mit einem Eintrag je Parameter (RESULT_SCHEMA). Daraus
entstehen Statuszeile und Ausgabeblock eines README-Blocks, DE und EN.
Kein Datum in der README: zwei Läufe ergäben sonst ohne Grund einen
Diff; die Frische sichert der pre-push-Hook (.beads/hooks/pre-push).
"""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

VERIFY = "make readme-check"
TEXT = {
    "README.md": {
        "passed": "bestanden",
        "failed": "fehlgeschlagen",
        "skipped": "ungeprüft",
        "stub": "ungeprüft",
        "not_run": "nicht ausgeführt",
        "verify": "selbst prüfen",
        "reason": "grund_de",
    },
    "README.en.md": {
        "passed": "passed",
        "failed": "failed",
        "skipped": "not checked",
        "stub": "not checked",
        "not_run": "not run",
        "verify": "verify",
        "reason": "grund_en",
    },
}
SYMBOL = {"passed": "✅", "failed": "❌", "skipped": "⏳", "stub": "⏳"}

_TEXT_FIELD = {"type": "string", "pattern": r"\S"}
RESULT_SCHEMA = Draft202012Validator(
    {
        "type": "array",
        "minItems": 1,
        "items": {
            "type": "object",
            "required": ["skript", "parameter", "ergebnis", "datum"],
            "additionalProperties": False,
            "properties": {
                "skript": {"type": "string", "pattern": r"^[^/]+\.sh$"},
                "parameter": {
                    "type": "object",
                    "additionalProperties": _TEXT_FIELD,
                },
                "ergebnis": {"enum": list(SYMBOL)},
                "grund_de": _TEXT_FIELD,
                "grund_en": _TEXT_FIELD,
                "datum": {
                    "type": "string",
                    "pattern": r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$",
                },
                "auszug": {
                    "type": "array",
                    "maxItems": 15,
                    "items": {"type": "string"},
                },
            },
            "allOf": [
                {
                    "if": {
                        "properties": {"ergebnis": {"const": "stub"}}
                    },
                    "then": {"required": ["grund_de", "grund_en"]},
                    "else": {
                        "not": {
                            "anyOf": [
                                {"required": ["grund_de"]},
                                {"required": ["grund_en"]},
                            ]
                        }
                    },
                },
                {
                    "if": {
                        "properties": {"ergebnis": {"const": "failed"}}
                    },
                    "then": {"not": {"required": ["auszug"]}},
                },
            ],
        },
    }
)


def load_results(
    directory: Path, scripts: set[str]
) -> tuple[dict[str, list[dict]], list[str]]:
    """Ergebnisse je Skriptname; ohne Datei fehlt das Skript."""
    results: dict[str, list[dict]] = {}
    problems: list[str] = []
    if not directory.is_dir():
        return results, [f"{directory}: kein Ergebnisverzeichnis"]
    for path in sorted(directory.glob("*.json")):
        script = f"{path.stem}.sh"
        entries, found = read_entries(path, script)
        if script not in scripts:
            found.append(f"{path.name}: kein README-Skript {script}")
        problems += found
        if not found:
            results[script] = entries
    return results, problems


def read_entries(
    path: Path, script: str
) -> tuple[list[dict], list[str]]:
    try:
        entries = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        return [], [f"{path.name}: kein JSON (Zeile {error.lineno})"]
    problems = [
        f"{path.name}: {field_path(error)}: {error.validator}"
        for error in RESULT_SCHEMA.iter_errors(entries)
    ]
    if problems:
        return [], problems
    return entries, entry_problems(path.name, script, entries)


def field_path(error) -> str:
    return "/".join(map(str, error.absolute_path)) or "(Wurzel)"


def entry_problems(
    name: str, script: str, entries: list[dict]
) -> list[str]:
    problems = [
        f"{name}: Eintrag {i}: skript {entry['skript']} statt {script}"
        for i, entry in enumerate(entries)
        if entry["skript"] != script
    ]
    parameters = [entry["parameter"] for entry in entries]
    if any(parameters.count(p) > 1 for p in parameters):
        problems.append(f"{name}: Parameter doppelt")
    return problems


def status_line(readme: str, entries: list[dict] | None) -> str:
    text = TEXT[readme]
    if entries is None:
        parts = [text["not_run"]]
    elif len(entries) == 1 and not entries[0]["parameter"]:
        parts = [single_status(text, entries[0])]
    else:
        parts = [parameter_status(text, entry) for entry in entries]
    parts.append(f"{text['verify']}: {VERIFY}")
    return "> " + " · ".join(parts)


def single_status(text: dict[str, str], entry: dict) -> str:
    result = entry["ergebnis"]
    status = f"{SYMBOL[result]} {text[result]}"
    if result == "stub":
        status += f" · {entry[text['reason']]}"
    return status


def parameter_status(text: dict[str, str], entry: dict) -> str:
    """Parameterwert statt Ergebnistext: ``✅ mock``, ``⏳ claude``."""
    result = entry["ergebnis"]
    label = " ".join(entry["parameter"].values())
    status = f"{SYMBOL[result]} {label}"
    if result == "stub":
        status += f" ({entry[text['reason']]})"
    return status


def excerpt(entries: list[dict] | None) -> list[str] | None:
    """Auszug des ersten bestandenen Eintrags; keiner bei failed."""
    if not entries or any(e["ergebnis"] == "failed" for e in entries):
        return None
    passed = (e for e in entries if e["ergebnis"] == "passed")
    return next((e["auszug"] for e in passed if e.get("auszug")), None)
