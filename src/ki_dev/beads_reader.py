"""Lesender Beads-Adapter: bd --readonly show BEAD_ID --json."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from jsonschema import Draft202012Validator
from plumbum import CommandNotFound, local
from plumbum.commands.processes import ProcessTimedOut, run_proc

from ki_dev.handoff import NONEMPTY_TEXT_SCHEMA, HandoffIssue

BD_PROGRAM = "bd"
BD_TIMEOUT_S = 10
# Feste Fehlerangabe von ``bd show --json`` (bd 1.3) auf stdout, wenn
# kein Bead zur ID existiert.
_BD_NOT_FOUND = "no issues found matching the provided IDs"

# Metadaten-Vertrag (Technikleitlinie): ``metadata`` und ``handoff``
# dürfen fehlen, vorhanden müssen es Objekte sein. ``source_refs``
# prüft der Kern (validate_handoff); unbekannte Felder bleiben erlaubt.
# Die Epic-Leitlinie gilt nur für Epics.
_METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "metadata": {
            "type": "object",
            "properties": {"handoff": {"type": "object"}},
        }
    },
}
_EPIC_METADATA_SCHEMA = {
    "type": "object",
    "properties": {
        "metadata": {
            "type": "object",
            "properties": {
                "handoff": {
                    "type": "object",
                    "properties": {
                        "guidance": {
                            **NONEMPTY_TEXT_SCHEMA,
                            "maxLength": 600,
                        }
                    },
                }
            },
        }
    },
}


class BeadsReadError(RuntimeError):
    """bd lieferte keinen brauchbaren Bead (Adapterfehler)."""


class InvalidBeadIdError(BeadsReadError):
    """Bead-ID ist leer oder sieht wie eine Option aus."""


def read_issue(bead_id: str, workdir: Path) -> HandoffIssue:
    """Einen Bead lesen und zu normalisierten Rohwerten machen."""
    raw = _read_raw(bead_id, workdir)
    _check_metadata(raw, _METADATA_SCHEMA)
    return replace(
        _normalize(raw), epic_guidance=_epic_guidance(raw, workdir)
    )


def _read_raw(bead_id: str, workdir: Path) -> dict:
    _check_bead_id(bead_id)
    stdout = _run_bd(
        ["--readonly", "show", bead_id, "--json"], workdir, bead_id
    )
    return _single_object(stdout, bead_id)


def _epic_guidance(
    raw: dict, workdir: Path
) -> tuple[tuple[str, str], ...]:
    hints: list[tuple[str, str]] = []
    seen = {raw["id"]}
    while parent := _parent(raw):
        if parent in seen:
            raise BeadsReadError("Zyklus in der Epic-Elternkette")
        seen.add(parent)
        raw = _read_raw(parent, workdir)
        is_epic = raw.get("issue_type") == "epic"
        _check_metadata(
            raw, _EPIC_METADATA_SCHEMA if is_epic else _METADATA_SCHEMA
        )
        if is_epic and (hint := _guidance(raw)) is not None:
            hints.append((parent, hint))
    return tuple(reversed(hints))


def _guidance(raw: dict) -> str | None:
    return raw.get("metadata", {}).get("handoff", {}).get("guidance")


def _check_metadata(raw: dict, schema: dict) -> None:
    """Ungültige Metadaten sichtbar ablehnen, nur mit Feldpfaden."""
    paths = {
        ".".join(str(part) for part in error.absolute_path)
        for error in Draft202012Validator(schema).iter_errors(raw)
    }
    if paths:
        raise BeadsReadError(
            f"Ungültige Metadaten in Bead {raw['id']}: "
            + ", ".join(sorted(paths))
        )


def _parent(raw: dict) -> str | None:
    dependencies = raw.get("dependencies", [])
    if not isinstance(dependencies, list) or any(
        not isinstance(item, dict) for item in dependencies
    ):
        raise BeadsReadError(
            "Ungültige Elternbeziehungen in bd-Antwort"
        )
    parents = [
        item.get("id")
        for item in dependencies
        if item.get("dependency_type") == "parent-child"
    ]
    if len(parents) > 1 or any(
        not isinstance(parent, str) or not parent.strip()
        for parent in parents
    ):
        raise BeadsReadError(
            "Ungültige oder mehrdeutige Elternbeziehung"
        )
    return next(iter(parents), None)


def _check_bead_id(bead_id: str) -> None:
    if not bead_id.strip() or bead_id.startswith("-"):
        raise InvalidBeadIdError(
            "BEAD_ID darf nicht leer sein und nicht mit '-' beginnen"
        )


def _run_bd(args: list[str], workdir: Path, bead_id: str) -> str:
    try:
        command = local[BD_PROGRAM][tuple(args)]
    except CommandNotFound:
        raise BeadsReadError("bd wurde nicht gefunden") from None
    try:
        code, stdout = _run_bytes(command, workdir)
        text = stdout.decode("utf-8")
    except ProcessTimedOut:
        raise BeadsReadError(
            f"bd antwortete nicht innerhalb von {BD_TIMEOUT_S} s"
        ) from None
    except FileNotFoundError:
        raise BeadsReadError("bd wurde nicht gefunden") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise BeadsReadError(
            f"bd konnte nicht gelesen werden ({type(exc).__name__})"
        ) from None
    if code != 0:
        raise BeadsReadError(_failure_message(code, text, bead_id))
    return text


def _run_bytes(command, workdir: Path) -> tuple[int, bytes]:
    """Plumbum ohne eigene Dekodierung: ``run`` würde nach der
    Locale-Kodierung mit errors="ignore" dekodieren und Zeichen still
    verlieren. Der Aufrufer dekodiert die Rohbytes strikt als UTF-8."""
    proc = command.popen(cwd=workdir)
    proc.custom_encoding = None
    code, stdout, _stderr = run_proc(proc, None, BD_TIMEOUT_S)
    return code, stdout


def _failure_message(code: int, stdout: str, bead_id: str) -> str:
    # Feste Ursachen: bd-Ausgabe könnte Roh-JSON enthalten und wird nie
    # übernommen, nur auf die bekannte Nicht-gefunden-Angabe geprüft.
    if _is_not_found(stdout):
        return f"Bead {bead_id} nicht gefunden"
    return f"bd endete mit Exit-Code {code}"


def _is_not_found(stdout: str) -> bool:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return False
    return isinstance(data, dict) and data.get("error") == _BD_NOT_FOUND


def _single_object(stdout: str, bead_id: str) -> dict:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise BeadsReadError("bd lieferte kein gültiges JSON") from exc
    if not (
        isinstance(data, list)
        and len(data) == 1
        and isinstance(data[0], dict)
    ):
        raise BeadsReadError(
            "bd-Antwort ist keine Liste mit genau einem Objekt"
        )
    if data[0].get("id") != bead_id:
        raise BeadsReadError(
            "bd lieferte einen Bead mit abweichender id"
        )
    return data[0]


def _normalize(raw: dict) -> HandoffIssue:
    return HandoffIssue(
        id=raw.get("id"),
        title=raw.get("title"),
        description=raw.get("description"),
        design=raw.get("design"),
        acceptance_criteria=raw.get("acceptance_criteria"),
        source_refs=_source_refs(raw),
    )


def _source_refs(raw: dict) -> object:
    # Form von metadata/handoff ist durch _check_metadata gesichert.
    return raw.get("metadata", {}).get("handoff", {}).get("source_refs")
