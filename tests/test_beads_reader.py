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


NOT_FOUND_STDOUT = json.dumps(
    {
        "error": "no issues found matching the provided IDs",
        "hint": "GEHEIMER-MARKER",
        "schema_version": 1,
    }
)


def test_missing_bead_is_named_without_bd_output(monkeypatch, tmp_path):
    _install(
        monkeypatch,
        returncode=1,
        stdout=NOT_FOUND_STDOUT,
        stderr="Issue x-1 not found\nGEHEIMER-MARKER",
    )
    with pytest.raises(BeadsReadError) as info:
        read_issue("x-1", tmp_path)
    assert str(info.value) == "Bead x-1 nicht gefunden"


@pytest.mark.parametrize(
    "stdout",
    [
        json.dumps({"error": "database is locked"}),
        json.dumps([{"error": "no issues found matching the provided IDs"}]),
        "Issue x-1 not found",
    ],
)
def test_similar_bd_failure_keeps_fixed_cause(
    monkeypatch, tmp_path, stdout
):
    _install(monkeypatch, returncode=1, stdout=stdout)
    with pytest.raises(BeadsReadError) as info:
        read_issue("x-1", tmp_path)
    assert str(info.value) == "bd endete mit Exit-Code 1"


def test_timeout_is_adapter_error(monkeypatch, tmp_path):
    _install(monkeypatch, raises=subprocess.TimeoutExpired(["bd"], 10))
    with pytest.raises(BeadsReadError, match="10 s"):
        read_issue("x-1", tmp_path)


def test_missing_bd_is_adapter_error(monkeypatch, tmp_path):
    _install(monkeypatch, raises=FileNotFoundError("bd"))
    with pytest.raises(BeadsReadError, match="nicht gefunden"):
        read_issue("x-1", tmp_path)


def _install_graph(monkeypatch, graph):
    calls = []

    def run(argv, **kwargs):
        assert argv[:3] == ["bd", "--readonly", "show"]
        calls.append(argv[3])
        return subprocess.CompletedProcess(
            argv, 0, json.dumps([graph[argv[3]]])
        )

    monkeypatch.setattr(beads_reader.subprocess, "run", run)
    return calls


def _node(key, parent=None, kind="task", hint=None):
    node = _bead(id=key, issue_type=kind)
    if parent:
        node["dependencies"] = [
            {"id": parent, "dependency_type": "parent-child"}
        ]
    if hint is not None:
        node["metadata"] = {"handoff": {"guidance": hint}}
    return node


def test_epic_guidance_inherits_through_tasks_in_root_order(
    monkeypatch, tmp_path
):
    graph = {
        "x-1": _node("x-1", "middle"),
        "middle": _node("middle", "inner", hint="not an epic"),
        "inner": _node("inner", "outer", "epic", "Specific"),
        "outer": _node("outer", kind="epic", hint="General"),
    }
    calls = _install_graph(monkeypatch, graph)
    issue = read_issue("x-1", tmp_path)
    assert issue.epic_guidance == (
        ("outer", "General"),
        ("inner", "Specific"),
    )
    assert calls == ["x-1", "middle", "inner", "outer"]


def test_blockers_and_origin_do_not_supply_guidance(
    monkeypatch, tmp_path
):
    node = _node("x-1")
    node["dependencies"] = [
        {"id": "other", "dependency_type": kind}
        for kind in ("blocks", "discovered-from")
    ]
    calls = _install_graph(monkeypatch, {"x-1": node})
    assert read_issue("x-1", tmp_path).epic_guidance == ()
    assert calls == ["x-1"]


@pytest.mark.parametrize("hint", ["", " ", 7, "x" * 601])
def test_invalid_epic_hint_is_visible_error(
    monkeypatch, tmp_path, hint
):
    _install_graph(
        monkeypatch,
        {
            "x-1": _node("x-1", "epic"),
            "epic": _node("epic", kind="epic", hint=hint),
        },
    )
    with pytest.raises(BeadsReadError, match="guidance"):
        read_issue("x-1", tmp_path)


def test_parent_cycle_is_visible_error(monkeypatch, tmp_path):
    _install_graph(
        monkeypatch,
        {
            "x-1": _node("x-1", "epic"),
            "epic": _node("epic", "x-1", "epic", "hint"),
        },
    )
    with pytest.raises(BeadsReadError, match="Zyklus"):
        read_issue("x-1", tmp_path)


@pytest.mark.parametrize(
    "dependencies",
    [
        None,
        [7],
        [
            {"id": "a", "dependency_type": "parent-child"},
            {"id": "b", "dependency_type": "parent-child"},
        ],
        [{"id": [], "dependency_type": "parent-child"}],
    ],
)
def test_invalid_parent_edges_fail_cleanly(
    monkeypatch, tmp_path, dependencies
):
    _install_graph(
        monkeypatch, {"x-1": _bead(dependencies=dependencies)}
    )
    with pytest.raises(BeadsReadError, match="Eltern"):
        read_issue("x-1", tmp_path)
