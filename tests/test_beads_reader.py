import json

import pytest
from plumbum import local

from ki_dev.ops.context import beads_reader
from ki_dev.ops.context.beads_reader import (
    BeadsReadError,
    InvalidBeadIdError,
    read_issue,
)
from tests.fake_bd_command import BdScript


def _bead(**changes):
    return {"id": "x-1", "title": "T", "description": "D"} | changes


def _install(monkeypatch, tmp_path, **values):
    fake = BdScript(tmp_path, **values)
    fake.install(monkeypatch)
    return fake


def test_only_the_allowed_read_call_is_made(monkeypatch, tmp_path):
    fake = _install(monkeypatch, tmp_path, stdout=json.dumps([_bead()]))
    read_issue("x-1", tmp_path)
    assert fake.calls == [["bd", "--readonly", "show", "x-1", "--json"]]
    assert fake.cwds == [str(tmp_path)]
    assert beads_reader.BD_TIMEOUT_S == 10


def test_normalizes_fields_and_ignores_extras(monkeypatch, tmp_path):
    bead = _bead(
        design="Dz",
        acceptance_criteria="AC",
        notes="N",
        comments=[{"text": "c"}],
        metadata={"handoff": {"source_refs": ["a.md#L1-L2"]}, "x": 1},
    )
    _install(monkeypatch, tmp_path, stdout=json.dumps([bead]))
    issue = read_issue("x-1", tmp_path)
    assert (issue.id, issue.title, issue.description) == (
        "x-1",
        "T",
        "D",
    )
    assert (issue.design, issue.acceptance_criteria) == ("Dz", "AC")
    assert issue.source_refs == ["a.md#L1-L2"]
    assert not hasattr(issue, "notes")


@pytest.mark.parametrize("metadata", [None, {}, {"handoff": {}}])
def test_missing_metadata_gives_no_refs(
    monkeypatch, tmp_path, metadata
):
    bead = _bead() if metadata is None else _bead(metadata=metadata)
    _install(monkeypatch, tmp_path, stdout=json.dumps([bead]))
    assert read_issue("x-1", tmp_path).source_refs is None


@pytest.mark.parametrize(
    ("metadata", "path"),
    [
        (None, "metadata"),
        ("text", "metadata"),
        ([], "metadata"),
        ({"handoff": None}, "metadata.handoff"),
        ({"handoff": 7}, "metadata.handoff"),
        ({"handoff": "text"}, "metadata.handoff"),
    ],
)
def test_invalid_metadata_is_rejected_with_field_path(
    monkeypatch, tmp_path, metadata, path
):
    bead = _bead(metadata=metadata)
    _install(monkeypatch, tmp_path, stdout=json.dumps([bead]))
    with pytest.raises(BeadsReadError) as info:
        read_issue("x-1", tmp_path)
    assert str(info.value) == f"Ungültige Metadaten in Bead x-1: {path}"


def test_invalid_metadata_message_has_no_raw_values(
    monkeypatch, tmp_path
):
    bead = _bead(metadata={"handoff": "GEHEIMER-MARKER"})
    _install(monkeypatch, tmp_path, stdout=json.dumps([bead]))
    with pytest.raises(BeadsReadError) as info:
        read_issue("x-1", tmp_path)
    assert "GEHEIMER-MARKER" not in str(info.value)


def test_wrong_typed_fields_are_kept_for_core_validation(
    monkeypatch, tmp_path
):
    _install(monkeypatch, tmp_path, stdout=json.dumps([_bead(title=7)]))
    assert read_issue("x-1", tmp_path).title == 7


@pytest.mark.parametrize("bead_id", ["", "  ", "-x", "--json"])
def test_invalid_ids_start_no_process(monkeypatch, tmp_path, bead_id):
    fake = _install(monkeypatch, tmp_path)
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
    _install(monkeypatch, tmp_path, stdout=stdout)
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
    _install(
        monkeypatch,
        tmp_path,
        returncode=3,
        stderr=stderr,
        stdout=stderr,
    )
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
        tmp_path,
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
        json.dumps(
            [{"error": "no issues found matching the provided IDs"}]
        ),
        "Issue x-1 not found",
    ],
)
def test_similar_bd_failure_keeps_fixed_cause(
    monkeypatch, tmp_path, stdout
):
    _install(monkeypatch, tmp_path, returncode=1, stdout=stdout)
    with pytest.raises(BeadsReadError) as info:
        read_issue("x-1", tmp_path)
    assert str(info.value) == "bd endete mit Exit-Code 1"


def test_timeout_is_adapter_error(monkeypatch, tmp_path):
    monkeypatch.setattr(beads_reader, "BD_TIMEOUT_S", 0.5)
    _install(monkeypatch, tmp_path, hang=True)
    with pytest.raises(BeadsReadError, match="0.5 s"):
        read_issue("x-1", tmp_path)


def test_missing_bd_is_adapter_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        beads_reader, "BD_PROGRAM", "kein-bd-vorhanden-xyz"
    )
    with pytest.raises(BeadsReadError, match="nicht gefunden"):
        read_issue("x-1", tmp_path)


def test_unstartable_bd_is_adapter_error(monkeypatch, tmp_path):
    fake = _install(monkeypatch, tmp_path)
    fake.break_interpreter()
    with pytest.raises(BeadsReadError, match="nicht gefunden"):
        read_issue("x-1", tmp_path)


def test_invalid_utf8_output_is_adapter_error(monkeypatch, tmp_path):
    raw = b'[{"id": "x-1", "title": "Pr\xfcfung"}]'
    _install(monkeypatch, tmp_path, stdout=raw)
    with pytest.raises(BeadsReadError) as info:
        read_issue("x-1", tmp_path)
    assert str(info.value) == (
        "bd konnte nicht gelesen werden (UnicodeDecodeError)"
    )


@pytest.mark.parametrize("encoding", ["ascii", "latin-1", "utf-8"])
def test_utf8_output_keeps_umlauts_independent_of_locale(
    monkeypatch, tmp_path, encoding
):
    # Plumbums Locale-Kodierung würde mit errors="ignore" dekodieren
    # ("Prüfung" -> "Prfung"); der Adapter liest Rohbytes strikt.
    monkeypatch.setattr(
        type(local), "custom_encoding", encoding, raising=False
    )
    bead = _bead(title="Prüfung für Übergabe")
    raw = json.dumps([bead], ensure_ascii=False).encode("utf-8")
    _install(monkeypatch, tmp_path, stdout=raw)
    assert read_issue("x-1", tmp_path).title == "Prüfung für Übergabe"


def _install_graph(monkeypatch, tmp_path, graph):
    return _install(monkeypatch, tmp_path, graph=graph)


def _node(key, parent=None, kind="task", hint=None):
    node = _bead(id=key, issue_type=kind)
    if parent:
        node["dependencies"] = [
            {"id": parent, "dependency_type": "parent-child"}
        ]
    if hint is not None:
        node["metadata"] = {"handoff": {"epic_context": hint}}
    return node


def test_epic_context_inherits_through_tasks_in_root_order(
    monkeypatch, tmp_path
):
    graph = {
        "x-1": _node("x-1", "middle"),
        "middle": _node("middle", "inner", hint="not an epic"),
        "inner": _node("inner", "outer", "epic", "Specific"),
        "outer": _node("outer", kind="epic", hint="General"),
    }
    fake = _install_graph(monkeypatch, tmp_path, graph)
    issue = read_issue("x-1", tmp_path)
    assert issue.epic_context == (
        ("outer", "General"),
        ("inner", "Specific"),
    )
    assert [call[3] for call in fake.calls] == [
        "x-1",
        "middle",
        "inner",
        "outer",
    ]


def test_blockers_and_origin_do_not_supply_epic_context(
    monkeypatch, tmp_path
):
    node = _node("x-1")
    node["dependencies"] = [
        {"id": "other", "dependency_type": kind}
        for kind in ("blocks", "discovered-from")
    ]
    fake = _install_graph(monkeypatch, tmp_path, {"x-1": node})
    assert read_issue("x-1", tmp_path).epic_context == ()
    assert [call[3] for call in fake.calls] == ["x-1"]


@pytest.mark.parametrize("hint", ["", " ", 7, "x" * 601])
def test_invalid_epic_hint_is_visible_error(
    monkeypatch, tmp_path, hint
):
    _install_graph(
        monkeypatch,
        tmp_path,
        {
            "x-1": _node("x-1", "epic"),
            "epic": _node("epic", kind="epic", hint=hint),
        },
    )
    with pytest.raises(BeadsReadError) as info:
        read_issue("x-1", tmp_path)
    assert str(info.value) == (
        "Ungültige Metadaten in Bead epic: "
        "metadata.handoff.epic_context"
    )


def test_null_epic_hint_is_visible_error(monkeypatch, tmp_path):
    epic = _node("epic", kind="epic")
    epic["metadata"] = {"handoff": {"epic_context": None}}
    _install_graph(
        monkeypatch,
        tmp_path,
        {"x-1": _node("x-1", "epic"), "epic": epic},
    )
    with pytest.raises(BeadsReadError, match="handoff.epic_context"):
        read_issue("x-1", tmp_path)


@pytest.mark.parametrize("handoff", [7, None, "text", []])
def test_invalid_epic_handoff_is_not_treated_as_missing(
    monkeypatch, tmp_path, handoff
):
    epic = _node("epic", kind="epic")
    epic["metadata"] = {"handoff": handoff}
    _install_graph(
        monkeypatch,
        tmp_path,
        {"x-1": _node("x-1", "epic"), "epic": epic},
    )
    with pytest.raises(BeadsReadError) as info:
        read_issue("x-1", tmp_path)
    assert str(info.value) == (
        "Ungültige Metadaten in Bead epic: metadata.handoff"
    )


@pytest.mark.parametrize("kind", ["epic", "task"])
def test_invalid_metadata_on_ancestors_is_rejected(
    monkeypatch, tmp_path, kind
):
    parent = _node("p", kind=kind)
    parent["metadata"] = "text"
    _install_graph(
        monkeypatch, tmp_path, {"x-1": _node("x-1", "p"), "p": parent}
    )
    with pytest.raises(BeadsReadError, match="metadata"):
        read_issue("x-1", tmp_path)


def test_epic_without_handoff_gives_no_epic_context(
    monkeypatch, tmp_path
):
    epic = _node("epic", kind="epic")
    epic["metadata"] = {"other": 1}
    _install_graph(
        monkeypatch,
        tmp_path,
        {"x-1": _node("x-1", "epic"), "epic": epic},
    )
    assert read_issue("x-1", tmp_path).epic_context == ()


def test_parent_cycle_is_visible_error(monkeypatch, tmp_path):
    _install_graph(
        monkeypatch,
        tmp_path,
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
        monkeypatch, tmp_path, {"x-1": _bead(dependencies=dependencies)}
    )
    with pytest.raises(BeadsReadError, match="Eltern"):
        read_issue("x-1", tmp_path)
