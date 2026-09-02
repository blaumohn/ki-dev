"""Parsing-Randfaelle der ``bd``-Ausgaben, ohne ``bd`` auszufuehren."""

from __future__ import annotations

from pathlib import Path

import pytest

from ki_dev.deltas import DeltaCommandError
from ki_dev.deltas import beads_changes as bc

_REPO = Path("/nicht/verwendet")


def _fixed_bd(payload: str):
    def _call(*_args: str) -> str:
        return payload

    return _call


def test_commit_field_accepts_valid_status():
    raw = '{"branch": "main", "commit": "abc123", "schema_version": 1}'
    assert bc._commit_field(raw) == "abc123"


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ('{"commit": null}', "commit-Feld"),
        ('{"commit": ""}', "commit-Feld"),
        ("{}", "commit-Feld"),
        ("[]", "kein Objekt"),
        ("kein json", "kein JSON"),
    ],
)
def test_commit_field_rejects_bad_status(raw: str, match: str):
    with pytest.raises(DeltaCommandError, match=match):
        bc._commit_field(raw)


def test_capture_beads_ref_uses_commit_field(monkeypatch):
    monkeypatch.setattr(bc, "_bd", _fixed_bd('{"commit": "deadbeef"}'))
    ref = bc.capture_beads_ref(_REPO)
    assert ref.value == "deadbeef"


def test_capture_beads_ref_rejects_null(monkeypatch):
    monkeypatch.setattr(bc, "_bd", _fixed_bd('{"commit": null}'))
    with pytest.raises(DeltaCommandError):
        bc.capture_beads_ref(_REPO)


def test_diff_issues_parses_valid_entries(monkeypatch):
    payload = (
        '[{"IssueID": "x-1", "DiffType": "added"},'
        ' {"IssueID": "x-2", "DiffType": "modified"}]'
    )
    monkeypatch.setattr(bc, "_bd", _fixed_bd(payload))
    issues = bc._diff_issues(_REPO, "a", "b")
    assert [i.issue_id for i in issues] == ["x-1", "x-2"]
    assert [i.change_type for i in issues] == ["added", "modified"]


@pytest.mark.parametrize(
    "payload",
    [
        "No changes between a and b",
        "No changes between a and b\n",
        "  No changes between a and b  \n",
    ],
)
def test_diff_issues_empty_on_no_changes(monkeypatch, payload: str):
    monkeypatch.setattr(bc, "_bd", _fixed_bd(payload))
    assert bc._diff_issues(_REPO, "a", "b") == ()


@pytest.mark.parametrize(
    "payload",
    [
        "No changes between x and y",
        "No changes between a and c",
        "No changes between a and b und noch etwas",
        "No changes between",
        "No changes between a and b\nNo changes between a and b",
    ],
)
def test_no_change_gilt_nur_fuer_diese_refs(monkeypatch, payload: str):
    """Die No-change-Meldung gilt nur fuer genau diese Referenzen."""
    monkeypatch.setattr(bc, "_bd", _fixed_bd(payload))
    with pytest.raises(DeltaCommandError, match="kein JSON"):
        bc._diff_issues(_REPO, "a", "b")


@pytest.mark.parametrize("payload", ["", "   ", "\n\t \n"])
def test_diff_issues_rejects_leere_ausgabe(monkeypatch, payload: str):
    """Leere Ausgabe ist kein leerer Delta, sondern ein Fehler."""
    monkeypatch.setattr(bc, "_bd", _fixed_bd(payload))
    with pytest.raises(DeltaCommandError, match="keine Ausgabe"):
        bc._diff_issues(_REPO, "a", "b")


@pytest.mark.parametrize(
    ("payload", "match"),
    [
        ('{"error": "branch not found"}', "bd diff meldete"),
        ('{"unerwartet": 1}', "keine Liste"),
        ("[1, 2]", "kein Objekt"),
        ('[{"IssueID": "x-1"}]', "Pflichtfelder"),
        ('[{"IssueID": 7, "DiffType": "added"}]', "Pflichtfelder"),
        ('[{"IssueID": "", "DiffType": "added"}]', "Pflichtfelder"),
        ('[{"IssueID": "  ", "DiffType": "added"}]', "Pflichtfelder"),
        ('[{"IssueID": "x-1", "DiffType": ""}]', "Pflichtfelder"),
        ('[{"IssueID": "x-1", "DiffType": " \\t "}]', "Pflichtfelder"),
        ('[{"IssueID": null, "DiffType": null}]', "Pflichtfelder"),
        ("kaputt", "kein JSON"),
    ],
)
def test_diff_issues_rejects_unexpected_json(
    monkeypatch, payload: str, match: str
):
    monkeypatch.setattr(bc, "_bd", _fixed_bd(payload))
    with pytest.raises(DeltaCommandError, match=match):
        bc._diff_issues(_REPO, "a", "b")
