import json
from dataclasses import replace

import pytest

from ki_dev import session_snapshot
from ki_dev.adapter.executors import codex_transcript
from ki_dev.session_snapshot import (
    LEGACY_FORMAT,
    SnapshotError,
    SnapshotTitleError,
    read_snapshot,
    serialize_snapshot,
    snapshot_stem,
    store_snapshot,
    title_slug,
)
from tests.codex_session_fixtures import (
    SECRET,
    dialog,
    jsonl,
    session_meta,
)

SID = "0199aaaa-bbbb-cccc-dddd-eeeeffff0001"
START = "2026-10-02T14:05:00Z"


def make(rows=None, start=START):
    meta = [session_meta(SID, start)] if start else []
    data = jsonl([*meta, *(rows or dialog(2))]).encode("utf-8")
    return codex_transcript.transcript_from_bytes(SID, data)


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_name_uses_utc_start_hour_slug_and_short_id():
    assert snapshot_stem(make(), "Session-Ausgabe") == (
        "261002T14_session-ausgabe_0199aaaa"
    )
    local = make(start="2026-10-02T23:30:00+02:00")
    assert snapshot_stem(local, "x").startswith("261002T21_")


@pytest.mark.parametrize(
    "start, stem",
    [
        ("2000-01-01T00:00:00Z", "000101T00"),
        ("2099-12-31T23:59:59Z", "991231T23"),
    ],
)
def test_century_bounds_are_accepted(start, stem):
    assert snapshot_stem(make(start=start), "x").startswith(stem)


@pytest.mark.parametrize(
    "start", ["1999-12-31T23:59:59Z", "2100-01-01T00:00:00Z"]
)
def test_outside_the_century_is_an_error(start):
    with pytest.raises(SnapshotError, match="2000-2099"):
        snapshot_stem(make(start=start), "x")


def test_missing_start_is_visible_not_replaced(tmp_path):
    with pytest.raises(SnapshotError, match="started_at fehlt"):
        store_snapshot(make(start=None), "x", tmp_path)
    assert not tmp_path.joinpath("x").exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "title, slug",
    [
        ("Größe Über Maß", "groesse-ueber-mass"),
        ("  Docker: A/B  ", "docker-a-b"),
        ("Café 2", "cafe-2"),
        ("a" * 30 + " " + "b" * 30, "a" * 30 + "-" + "b" * 9),
    ],
)
def test_slug_is_safe_and_deterministic(title, slug):
    assert title_slug(title) == slug


@pytest.mark.parametrize("title", ["", " ", "!!!", "x" * 121, None, 5])
def test_invalid_titles_are_rejected_before_any_write(tmp_path, title):
    with pytest.raises(SnapshotTitleError):
        store_snapshot(make(), title, tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_header_comes_first_and_is_not_a_message(tmp_path):
    transcript = make()
    path = store_snapshot(transcript, "Titel", tmp_path)
    header, *messages = lines(path)
    assert header == {
        "type": "transcript_meta",
        "version": 1,
        "agent": "codex",
        "session_id": SID,
        "started_at": START,
        "last_activity_at": transcript.last_activity_at,
        "title": "Titel",
        "source_digest": transcript.source_digest,
        "parser_version": transcript.parser_version,
        "diagnostics": dict(transcript.diagnostics),
    }
    assert [m["type"] for m in messages] == ["message"] * 4
    snapshot = read_snapshot(path)
    assert snapshot.title == "Titel"
    assert snapshot.transcript == transcript
    assert len(snapshot.transcript.messages) == 4


def test_serialization_is_deterministic():
    assert serialize_snapshot(make(), "T") == serialize_snapshot(
        make(), "T"
    )


def test_repeat_reuses_the_file_even_with_another_title(tmp_path):
    path = store_snapshot(make(), "Titel", tmp_path)
    before = path.stat().st_mtime_ns
    assert store_snapshot(make(), "Titel", tmp_path) == path
    assert store_snapshot(make(), "Anders", tmp_path) == path
    assert path.stat().st_mtime_ns == before
    assert len(list(tmp_path.iterdir())) == 1


def test_new_source_state_gets_a_digest_suffix(tmp_path):
    old = store_snapshot(make(dialog(2)), "T", tmp_path)
    old_bytes = old.read_bytes()
    new_transcript = make(dialog(3))
    new = store_snapshot(new_transcript, "T", tmp_path)
    digest = new_transcript.source_digest
    assert new.name == f"261002T14_t_0199aaaa-{digest[:8]}.jsonl"
    assert old.read_bytes() == old_bytes


def test_short_suffix_collision_is_extended(tmp_path):
    first = store_snapshot(make(dialog(2)), "T", tmp_path)
    third = make(dialog(4))
    digest = third.source_digest
    taken = tmp_path / f"{first.stem}-{digest[:8]}.jsonl"
    taken.write_bytes(first.read_bytes())
    path = store_snapshot(third, "T", tmp_path)
    assert path.name == f"{first.stem}-{digest[:12]}.jsonl"
    assert taken.read_bytes() == first.read_bytes()


def test_same_key_with_different_content_is_an_error(tmp_path):
    path = store_snapshot(make(), "T", tmp_path)
    rows = lines(path)
    rows[1]["text"] = "veraendert"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    before = path.read_bytes()
    with pytest.raises(SnapshotError, match="abweichender Inhalt"):
        store_snapshot(make(), "T", tmp_path)
    assert path.read_bytes() == before


def test_failed_publication_leaves_no_file(tmp_path, monkeypatch):
    def broken(*_args):
        raise OSError("voll")

    monkeypatch.setattr(session_snapshot.os, "link", broken)
    with pytest.raises(SnapshotError, match="nicht ablegbar"):
        store_snapshot(make(), "T", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_existing_target_is_never_overwritten(tmp_path, monkeypatch):
    """Ein zwischenzeitlich belegter Name fuehrt zum naechsten Namen."""
    transcript = make()
    stem = snapshot_stem(transcript, "T")
    real_exists = session_snapshot.Path.exists

    def racing(path):
        if path.name == f"{stem}.jsonl" and not real_exists(path):
            path.write_text("fremd\n")
            return False
        return real_exists(path)

    monkeypatch.setattr(session_snapshot.Path, "exists", racing)
    path = store_snapshot(transcript, "T", tmp_path)
    assert path.name.startswith(f"{stem}-")
    assert (tmp_path / f"{stem}.jsonl").read_text() == "fremd\n"


def test_unwritable_directory_is_a_sanitized_error(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("kein Verzeichnis")
    with pytest.raises(SnapshotError, match="nicht ablegbar"):
        store_snapshot(make(), "T", blocker / "sub")


def _write(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda rows: rows[:1], "Feld <root> (minItems)"),
        (lambda rows: [rows[1], rows[0], *rows[2:]], "Feld [0]"),
        (lambda rows: [*rows, rows[0]], "Feld [5]"),
        (
            lambda rows: [rows[0] | {"version": 2}, *rows[1:]],
            "Feld [0].version (const)",
        ),
        (
            lambda rows: [rows[0] | {"extra": SECRET}, *rows[1:]],
            "(additionalProperties)",
        ),
        (
            lambda rows: [
                rows[0],
                rows[1] | {"role": SECRET},
                *rows[2:],
            ],
            "messages[0].role",
        ),
    ],
)
def test_invalid_v1_documents_name_the_field_only(
    tmp_path, mutate, needle
):
    path = store_snapshot(make(), "T", tmp_path)
    _write(path, mutate(lines(path)))
    with pytest.raises(SnapshotError) as info:
        read_snapshot(path)
    assert needle in str(info.value)
    assert SECRET not in str(info.value)


def test_broken_json_line_is_reported_by_number(tmp_path):
    path = store_snapshot(make(), "T", tmp_path)
    path.write_text(path.read_text() + '{"type": "mess')
    with pytest.raises(SnapshotError, match="Zeile 6 ist kein JSON"):
        read_snapshot(path)


def test_legacy_handoff_files_are_read_without_invented_metadata(
    tmp_path,
):
    transcript = make()
    name = f"{transcript.source_digest}-{transcript.parser_version}"
    path = tmp_path / ".local/handoff/codex" / SID / f"{name}.jsonl"
    path.parent.mkdir(parents=True)
    _write(path, lines(store_snapshot(transcript, "T", tmp_path))[1:])
    rows = lines(path)
    for row in rows:
        row.pop("type")
    _write(path, rows)
    snapshot = read_snapshot(path)
    assert snapshot.format == LEGACY_FORMAT
    assert snapshot.title is None
    assert snapshot.transcript.started_at is None
    assert snapshot.transcript.messages == transcript.messages
    assert snapshot.transcript.source_digest == transcript.source_digest


def test_legacy_rows_outside_the_known_path_are_rejected(tmp_path):
    rows = lines(store_snapshot(make(), "T", tmp_path))[1:]
    for row in rows:
        row.pop("type")
    path = _write(tmp_path / "irgendwo.jsonl", rows)
    with pytest.raises(SnapshotError, match=LEGACY_FORMAT):
        read_snapshot(path)


@pytest.mark.parametrize(
    "row",
    [
        {"role": "benutzer", "text": SECRET, "timestamp": START},
        {"ordinal": 1, "role": "agent", "text": SECRET},
    ],
)
def test_unknown_formats_are_rejected_with_keys_only(tmp_path, row):
    path = _write(tmp_path / "planning.jsonl", [row])
    with pytest.raises(SnapshotError) as info:
        read_snapshot(path)
    message = str(info.value)
    assert "unbekanntes Snapshot-Format" in message
    assert "role, text" in message
    assert SECRET not in message


def test_transcript_contract_violation_is_never_written(tmp_path):
    transcript = make()
    broken = replace(transcript, messages=())
    with pytest.raises(SnapshotError, match="Vertrag"):
        store_snapshot(broken, "T", tmp_path)
    assert list(tmp_path.iterdir()) == []
