import json
import subprocess

import pytest

from ki_dev import beads_reader
from ki_dev.beads_reader import (
    BeadsReadError,
    InvalidBeadIdError,
    read_issue,
)


class FakeBd:
    def __init__(self, stdout="", returncode=0, stderr="", raises=None):
        self.result = subprocess.CompletedProcess(
            [], returncode, stdout, stderr
        )
        self.raises = raises
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if self.raises:
            raise self.raises
        return self.result


def _bead(**changes):
    return {"id": "x-1", "title": "T", "description": "D"} | changes


def _install(monkeypatch, **kwargs):
    fake = FakeBd(**kwargs)
    monkeypatch.setattr(beads_reader.subprocess, "run", fake)
    return fake


def test_only_the_allowed_read_call_is_made(monkeypatch, tmp_path):
    fake = _install(monkeypatch, stdout=json.dumps([_bead()]))
    read_issue("x-1", tmp_path)
    [(argv, kwargs)] = fake.calls
    assert argv == ["bd", "--readonly", "show", "x-1", "--json"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["timeout"] == 10
    assert not kwargs.get("shell")


def test_normalizes_fields_and_ignores_extras(monkeypatch, tmp_path):
    bead = _bead(
        design="Dz",
        acceptance_criteria="AC",
        notes="N",
        comments=[{"text": "c"}],
        metadata={"handoff": {"source_refs": ["a.md#L1-L2"]}, "x": 1},
    )
    _install(monkeypatch, stdout=json.dumps([bead]))
    issue = read_issue("x-1", tmp_path)
    assert (issue.id, issue.title, issue.description) == (
        "x-1",
        "T",
        "D",
    )
    assert (issue.design, issue.acceptance_criteria) == ("Dz", "AC")
    assert issue.source_refs == ["a.md#L1-L2"]
    assert not hasattr(issue, "notes")


@pytest.mark.parametrize(
    "metadata",
    [None, "text", [], {}, {"handoff": None}, {"handoff": 3}],
)
def test_missing_or_misshapen_metadata_gives_no_refs(
    monkeypatch, tmp_path, metadata
):
    bead = _bead() if metadata is None else _bead(metadata=metadata)
    _install(monkeypatch, stdout=json.dumps([bead]))
    assert read_issue("x-1", tmp_path).source_refs is None


def test_wrong_typed_fields_are_kept_for_core_validation(
    monkeypatch, tmp_path
):
    _install(monkeypatch, stdout=json.dumps([_bead(title=7)]))
    assert read_issue("x-1", tmp_path).title == 7


@pytest.mark.parametrize("bead_id", ["", "  ", "-x", "--json"])
def test_invalid_ids_start_no_process(monkeypatch, tmp_path, bead_id):
    fake = _install(monkeypatch)
    with pytest.raises(InvalidBeadIdError):
        read_issue(bead_id, tmp_path)
    assert fake.calls == []


@pytest.mark.parametrize(
    "stdout",
    [
        "kein json",
        "{}",
        "[]",
        json.dumps([_bead(), _bead()]),
        json.dumps(["x-1"]),
        json.dumps({"id": "x-1"}),
        json.dumps([_bead(id="andere-1")]),
        json.dumps([{"title": "ohne id"}]),
    ],
)
def test_wrong_shape_or_id_mismatch_is_adapter_error(
    monkeypatch, tmp_path, stdout
):
    _install(monkeypatch, stdout=stdout)
    with pytest.raises(BeadsReadError) as info:
        read_issue("x-1", tmp_path)
    assert stdout not in str(info.value)


@pytest.mark.parametrize(
    "stderr",
    [
        "Fehler: nicht gefunden\n" + "Rohdump\n" * 50,
        '{"id": "x-1", "notes": "GEHEIMER-MARKER"}',
        '{"error": "GEHEIMER-MARKER"}\nzweite Zeile',
    ],
)
def test_process_failure_reports_fixed_cause_only(
    monkeypatch, tmp_path, stderr
):
    _install(monkeypatch, returncode=3, stderr=stderr, stdout=stderr)
    with pytest.raises(BeadsReadError) as info:
        read_issue("x-1", tmp_path)
    assert str(info.value) == "bd endete mit Exit-Code 3"


def test_timeout_is_adapter_error(monkeypatch, tmp_path):
    _install(monkeypatch, raises=subprocess.TimeoutExpired(["bd"], 10))
    with pytest.raises(BeadsReadError, match="10 s"):
        read_issue("x-1", tmp_path)


def test_missing_bd_is_adapter_error(monkeypatch, tmp_path):
    _install(monkeypatch, raises=FileNotFoundError("bd"))
    with pytest.raises(BeadsReadError, match="nicht gefunden"):
        read_issue("x-1", tmp_path)
