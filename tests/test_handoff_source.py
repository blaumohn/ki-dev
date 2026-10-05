import json
import os
from pathlib import Path

import pytest

from ki_dev import handoff_source
from ki_dev.executors import codex_transcript
from ki_dev.handoff_source import (
    HandoffSourceError,
    serialize_messages,
    source_key,
    source_path,
    store_source,
)
from tests.codex_session_fixtures import dialog, jsonl

SID = "0199aaaa-bbbb-cccc-dddd-eeeeffff0001"


def make(rows=None):
    data = jsonl(rows or dialog(2)).encode("utf-8")
    return codex_transcript.transcript_from_bytes(SID, data)


def test_key_and_path_follow_the_source_state():
    transcript = make()
    assert source_key(transcript) == (
        f"codex:{SID}:{transcript.source_digest}:"
        f"{transcript.parser_version}"
    )
    assert source_path(transcript) == Path(
        f".local/handoff/codex/{SID}/"
        f"{transcript.source_digest}-{transcript.parser_version}.jsonl"
    )


def test_serialization_is_one_message_per_line_and_deterministic():
    transcript = make()
    content = serialize_messages(transcript)
    lines = content.decode("utf-8").splitlines()
    assert len(lines) == len(transcript.messages) == 4
    first = json.loads(lines[0])
    assert set(first) == {
        "position",
        "ordinal",
        "role",
        "text",
        "source_line",
        "timestamp",
    }
    assert first["source_line"] == 1
    assert content == serialize_messages(make())


def test_store_writes_the_artifact_and_returns_the_relative_path(
    tmp_path,
):
    transcript = make()
    relative = store_source(transcript, tmp_path)
    assert not relative.is_absolute()
    assert (tmp_path / relative).read_bytes() == serialize_messages(
        transcript
    )
    assert [p.name for p in (tmp_path / relative).parent.iterdir()] == [
        relative.name
    ]


def test_identical_artifact_is_reused_without_rewriting(tmp_path):
    transcript = make()
    relative = store_source(transcript, tmp_path)
    target = tmp_path / relative
    before = target.stat().st_mtime_ns
    assert store_source(transcript, tmp_path) == relative
    assert target.stat().st_mtime_ns == before


def test_different_content_at_the_same_key_is_an_error(tmp_path):
    transcript = make()
    target = tmp_path / store_source(transcript, tmp_path)
    target.write_text("veraendert\n")
    with pytest.raises(HandoffSourceError, match="abweichend"):
        store_source(transcript, tmp_path)
    assert target.read_text() == "veraendert\n"


def test_changed_session_bytes_get_a_new_path_and_keep_the_old(
    tmp_path,
):
    old = make(dialog(2))
    new = make(dialog(3))
    old_path = store_source(old, tmp_path)
    new_path = store_source(new, tmp_path)
    assert old_path != new_path
    assert (tmp_path / old_path).read_bytes() == serialize_messages(old)


def test_failed_publication_leaves_neither_target_nor_temp_file(
    tmp_path, monkeypatch
):
    def broken(*_args):
        raise OSError("voll")

    monkeypatch.setattr(handoff_source.os, "replace", broken)
    transcript = make()
    with pytest.raises(HandoffSourceError, match="nicht ablegbar"):
        store_source(transcript, tmp_path)
    directory = tmp_path / source_path(transcript).parent
    assert list(directory.iterdir()) == []


def test_unwritable_target_is_a_sanitized_error(tmp_path):
    (tmp_path / ".local").write_text("keine Verzeichnis")
    with pytest.raises(HandoffSourceError, match="nicht ablegbar"):
        store_source(make(), tmp_path)


@pytest.mark.parametrize("bad", ["../x", "a/b", "", ".hidden", "a b"])
def test_unsafe_key_components_are_rejected(bad):
    transcript = make()
    object.__setattr__(transcript, "session_id", bad)
    with pytest.raises(HandoffSourceError, match="unsicher"):
        source_path(transcript)


def test_os_module_is_the_only_publication_primitive():
    assert handoff_source.os is os
