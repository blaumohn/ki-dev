from pathlib import Path

import pytest

from ki_dev.executors import codex_transcript
from ki_dev.handoff_source import (
    HandoffSourceError,
    accepted_refs,
    legacy_source_path,
    source_key,
    store_source,
)
from tests.codex_session_fixtures import dialog, jsonl, session_meta

SID = "0199aaaa-bbbb-cccc-dddd-eeeeffff0001"


def make(rows=None):
    rows = [session_meta(SID), *(rows or dialog(2))]
    data = jsonl(rows).encode("utf-8")
    return codex_transcript.transcript_from_bytes(SID, data)


def test_key_and_legacy_path_follow_the_source_state():
    transcript = make()
    assert source_key(transcript) == (
        f"codex:{SID}:{transcript.source_digest}:"
        f"{transcript.parser_version}"
    )
    assert legacy_source_path(transcript) == Path(
        f".local/handoff/codex/{SID}/"
        f"{transcript.source_digest}-{transcript.parser_version}.jsonl"
    )


def test_store_uses_the_shared_snapshot_directory(tmp_path):
    relative = store_source(make(), "Quelle", tmp_path)
    assert not relative.is_absolute()
    assert relative == Path(
        ".local/var/transcripts/260917T09_quelle_0199aaaa.jsonl"
    )
    assert (tmp_path / relative).is_file()


def test_snapshot_errors_become_source_errors(tmp_path):
    (tmp_path / ".local").write_text("kein Verzeichnis")
    with pytest.raises(HandoffSourceError, match="nicht ablegbar"):
        store_source(make(), "Quelle", tmp_path)


def test_legacy_reference_is_accepted_only_if_present(tmp_path):
    transcript = make()
    stored = store_source(transcript, "Quelle", tmp_path)
    assert accepted_refs(transcript, stored, tmp_path) == (
        stored.as_posix(),
    )
    legacy = tmp_path / legacy_source_path(transcript)
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}\n")
    assert accepted_refs(transcript, stored, tmp_path) == (
        stored.as_posix(),
        legacy_source_path(transcript).as_posix(),
    )


@pytest.mark.parametrize("bad", ["../x", "a/b", "", ".hidden", "a b"])
def test_unsafe_key_components_are_rejected(bad):
    transcript = make()
    object.__setattr__(transcript, "session_id", bad)
    with pytest.raises(HandoffSourceError, match="unsicher"):
        legacy_source_path(transcript)
