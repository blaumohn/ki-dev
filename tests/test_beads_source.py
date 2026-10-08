import pytest

from ki_dev.step import beads_source
from ki_dev.step.beads_source import (
    BeadsSourceError,
    SourceBead,
    ensure_source_bead,
    find_source_bead,
)
from tests.codex_session_fixtures import SECRET
from tests.fake_bd import FakeBd

KEY = "codex:abc:d1:v1"
SOURCE = SourceBead(
    key=KEY,
    title="Quelle: codex-Sitzung abc",
    description="Beschreibung ohne Inhalt",
    source_ref=".local/handoff/codex/abc/d1-v1.jsonl",
)


@pytest.fixture
def bd(tmp_path, monkeypatch):
    fake = FakeBd(tmp_path, SECRET)
    fake.install(monkeypatch)
    return fake


def row(bead_id, key, **extra):
    return {
        "id": bead_id,
        "metadata": {"handoff": {"source_key": key}},
    } | extra


def test_absent_key_creates_one_bead_and_confirms_it(bd, tmp_path):
    assert ensure_source_bead(SOURCE, tmp_path) == "t-1"
    assert bd.commands() == ["list", "create", "list"]
    [created] = bd.rows
    assert created["metadata"]["handoff"] == {
        "source_key": KEY,
        "source_refs": [SOURCE.source_ref],
    }
    assert created["title"] == SOURCE.title


def test_existing_bead_is_reused_without_create(bd, tmp_path):
    bd.set(rows=[row("t-9", KEY)])
    assert ensure_source_bead(SOURCE, tmp_path) == "t-9"
    assert bd.commands() == ["list"]


def test_list_reads_everything_including_closed(bd, tmp_path):
    bd.set(rows=[row("t-9", KEY, status="closed")])
    assert find_source_bead(KEY, tmp_path) == "t-9"
    [call] = bd.get()["calls"]
    assert "--all" in call
    assert call[call.index("-n") + 1] == "0"


def test_key_is_compared_exactly(bd, tmp_path):
    bd.set(
        rows=[
            row("t-1", KEY + "x"),
            row("t-2", "x" + KEY),
            row("t-3", None),
        ]
    )
    assert find_source_bead(KEY, tmp_path) is None


def test_foreign_metadata_shapes_are_tolerated(bd, tmp_path):
    bd.set(
        rows=[
            {"id": "t-1", "metadata": "text"},
            {"id": "t-2", "metadata": {"handoff": "text"}},
            {"id": "t-3"},
            row("t-4", KEY),
        ]
    )
    assert find_source_bead(KEY, tmp_path) == "t-4"


def test_several_beads_for_one_key_abort_without_create(bd, tmp_path):
    bd.set(rows=[row("t-1", KEY), row("t-2", KEY)])
    with pytest.raises(BeadsSourceError, match="2 Quellen-Beads"):
        ensure_source_bead(SOURCE, tmp_path)
    assert "create" not in bd.commands()


def test_matching_row_without_id_is_an_error(bd, tmp_path):
    bd.set(rows=[row("t-1", KEY) | {"id": ""}])
    with pytest.raises(BeadsSourceError, match="id"):
        find_source_bead(KEY, tmp_path)


def test_unconfirmed_creation_is_an_error(bd, tmp_path):
    bd.set(create_nothing=True)
    with pytest.raises(BeadsSourceError, match="nicht bestaetigt"):
        ensure_source_bead(SOURCE, tmp_path)


@pytest.mark.parametrize("command", ["list", "create"])
def test_bd_failure_is_sanitized(bd, tmp_path, command):
    bd.set(fail_on=command)
    with pytest.raises(BeadsSourceError) as caught:
        ensure_source_bead(SOURCE, tmp_path)
    assert "Exit-Code 3" in str(caught.value)
    assert SECRET not in str(caught.value)


def test_bd_timeout_is_an_error(bd, tmp_path, monkeypatch):
    monkeypatch.setattr(beads_source, "BD_TIMEOUT_S", 0.5)
    bd.set(hang="list")
    with pytest.raises(BeadsSourceError, match="nicht innerhalb"):
        find_source_bead(KEY, tmp_path)


def test_missing_bd_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr(
        beads_source, "BD_PROGRAM", str(tmp_path / "gibt-es-nicht")
    )
    with pytest.raises(BeadsSourceError, match="nicht gefunden"):
        find_source_bead(KEY, tmp_path)


def test_garbled_output_is_an_error_without_echo(tmp_path, monkeypatch):
    script = tmp_path / "bd"
    script.write_text(f"#!/bin/sh\necho '{SECRET} kein json'\n")
    script.chmod(0o755)
    monkeypatch.setattr(beads_source, "BD_PROGRAM", str(script))
    with pytest.raises(BeadsSourceError) as caught:
        find_source_bead(KEY, tmp_path)
    assert SECRET not in str(caught.value)


def test_arguments_are_a_vector_not_a_shell_string(bd, tmp_path):
    hostile = SourceBead(
        key=KEY,
        title="x; rm -rf / $(id)",
        description="`id` && echo",
        source_ref="p",
    )
    ensure_source_bead(hostile, tmp_path)
    assert bd.rows[0]["title"] == "x; rm -rf / $(id)"
    assert bd.rows[0]["description"] == "`id` && echo"
