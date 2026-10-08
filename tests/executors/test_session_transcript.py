import dataclasses

import pytest

from ki_dev.adapter.executors import claude_transcript, codex_transcript
from ki_dev.adapter.executors.session_transcript import (
    SessionTranscript,
    TranscriptError,
    dialog_advisories,
    require_started_at,
    validate_transcript,
)
from tests import claude_session_fixtures as claude
from tests import codex_session_fixtures as codex
from tests.codex_session_fixtures import SECRET

CODEX_SID = "0199aaaa-bbbb-cccc-dddd-eeeeffff0001"


def codex_transcript_of(rows):
    data = codex.jsonl(rows).encode("utf-8")
    return codex_transcript.transcript_from_bytes(CODEX_SID, data)


def claude_transcript_of(rows):
    data = claude.jsonl(rows).encode("utf-8")
    return claude_transcript.transcript_from_bytes(claude.SESSION, data)


def session_meta(timestamp, session_id=CODEX_SID):
    return {
        "type": "session_meta",
        "timestamp": "2026-10-05T09:59:59.000Z",
        "payload": {"id": session_id, "timestamp": timestamp},
    }


def contract_problems(transcript) -> str:
    with pytest.raises(TranscriptError) as caught:
        validate_transcript(transcript)
    return "\n".join(caught.value.problems)


def test_both_providers_deliver_the_same_validated_type():
    results = [
        codex_transcript_of(codex.dialog(1)),
        claude_transcript_of(claude.dialog(1)),
    ]
    for transcript in results:
        assert type(transcript) is SessionTranscript
        validate_transcript(transcript)
    assert {t.agent for t in results} == {"codex", "claude"}
    assert [type(f) for f in dataclasses.fields(results[0])] == [
        type(f) for f in dataclasses.fields(results[1])
    ]


@pytest.mark.parametrize(
    "change, path",
    [
        ({"agent": "gemini"}, "agent"),
        ({"source_digest": SECRET}, "source_digest"),
        ({"started_at": SECRET}, "started_at"),
        ({"messages": ()}, "messages"),
        ({"diagnostics": {"T1": -1}}, "diagnostics.T1"),
    ],
)
def test_in_memory_violations_name_the_field_without_the_value(
    change, path
):
    transcript = dataclasses.replace(
        claude_transcript_of(claude.dialog(1)), **change
    )
    text = contract_problems(transcript)
    assert f"Feld {path}" in text
    assert SECRET not in text


def test_in_memory_message_violations_are_detected():
    transcript = claude_transcript_of(claude.dialog(1))
    first = transcript.messages[0]
    broken = [
        dataclasses.replace(first, role="system"),
        dataclasses.replace(first, text="  "),
        dataclasses.replace(first, position=3),
        dataclasses.replace(first, ordinal=1),
        dataclasses.replace(first, timestamp="2026-02-30T00:00:00Z"),
    ]
    for message in broken:
        messages = (message, *transcript.messages[1:])
        problems = contract_problems(
            dataclasses.replace(transcript, messages=messages)
        )
        assert "Vertrag" in problems


@pytest.mark.parametrize(
    "change, path",
    [
        ({"messages": None}, "messages"),
        ({"messages": SECRET}, "messages"),
        ({"messages": (None,)}, "messages[0]"),
        ({"messages": ({"role": "user"},)}, "messages[0]"),
        ({"diagnostics": None}, "diagnostics"),
        ({"diagnostics": {"lines": True}}, "diagnostics.lines"),
        ({"session_id": None}, "session_id"),
    ],
)
def test_wrong_python_types_are_contract_errors_not_crashes(
    change, path
):
    transcript = dataclasses.replace(
        claude_transcript_of(claude.dialog(1)), **change
    )
    text = contract_problems(transcript)
    assert f"Feld {path} (type)" in text
    assert SECRET not in text


def test_non_transcript_objects_are_rejected():
    for value in (None, {"agent": "claude"}):
        with pytest.raises(
            TranscriptError, match="kein SessionTranscript"
        ):
            validate_transcript(value)


def test_last_activity_before_start_is_a_contract_error():
    transcript = dataclasses.replace(
        claude_transcript_of(claude.dialog(1)),
        last_activity_at="2020-01-01T00:00:00Z",
    )
    assert "vor started_at" in contract_problems(transcript)


def test_codex_start_comes_from_session_meta_of_this_session():
    rows = [session_meta("2026-10-05T09:00:00.000Z"), *codex.dialog(1)]
    transcript = codex_transcript_of(rows)
    assert transcript.started_at == "2026-10-05T09:00:00.000Z"
    assert transcript.last_activity_at == transcript.started_at


def test_codex_session_meta_of_another_session_is_no_evidence():
    rows = [
        session_meta("2026-10-05T09:00:00Z", "fremd"),
        *codex.dialog(1),
    ]
    assert codex_transcript_of(rows).started_at is None


def test_codex_invalid_or_contradictory_start_is_an_error():
    rows = [session_meta(SECRET), *codex.dialog(1)]
    with pytest.raises(TranscriptError) as caught:
        codex_transcript_of(rows)
    assert "T8" in str(caught.value) and SECRET not in str(caught.value)
    rows = [
        session_meta("2026-10-05T09:00:00Z"),
        session_meta("2026-10-05T08:00:00Z"),
        *codex.dialog(1),
    ]
    with pytest.raises(TranscriptError, match="widerspruechliche"):
        codex_transcript_of(rows)


def test_codex_message_timestamps_are_optional_but_checked():
    rows = codex.dialog(1)
    rows[1]["timestamp"] = "2026-10-05T09:30:00Z"
    transcript = codex_transcript_of(rows)
    assert [m.timestamp for m in transcript.messages] == [
        None,
        "2026-10-05T09:30:00Z",
    ]
    assert transcript.last_activity_at == "2026-10-05T09:30:00Z"
    rows[1]["timestamp"] = SECRET
    with pytest.raises(TranscriptError) as caught:
        codex_transcript_of(rows)
    assert "Zeile 2 timestamp" in str(caught.value)
    assert SECRET not in str(caught.value)


def test_missing_start_keeps_display_but_dated_export_fails_visibly():
    transcript = codex_transcript_of(codex.dialog(1))
    assert transcript.started_at is None
    assert len(transcript.messages) == 2
    with pytest.raises(TranscriptError, match="started_at fehlt"):
        require_started_at(transcript)


@pytest.mark.parametrize(
    "roles, expected",
    [
        ([], (0, 0, 0)),
        (["user"], (1, 0, 0)),
        (["assistant"], (1, 0, 1)),
        (["user", "assistant"], (0, 0, 0)),
        (["user", "assistant", "user"], (0, 1, 0)),
        (["user", "user", "assistant", "assistant"], (0, 0, 2)),
    ],
)
def test_dialog_advisories(roles, expected):
    result = dialog_advisories(roles)
    assert (
        result["T1_single_role"],
        result["T2_count_mismatch"],
        result["T4_role_breaks"],
    ) == expected
