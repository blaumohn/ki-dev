import contextlib
import hashlib
import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ki_dev.executors import codex_transcript
from ki_dev.executors.codex_sessions import (
    find_session_rollout,
    resolve_codex_sessions_dir,
)
from ki_dev.executors.session_transcript import (
    TranscriptError,
    TranscriptRequestError,
)
from ki_dev.executors.transcript import (
    read_session_transcript,
    transcript_agents,
    validate_session_request,
)
from tests.codex_session_fixtures import (
    SECRET,
    assistant,
    dialog,
    jsonl,
    noise,
    user,
    write_session,
)

SID = "0199aaaa-bbbb-cccc-dddd-eeeeffff0001"


def extract(rows_or_text):
    text = (
        rows_or_text
        if isinstance(rows_or_text, str)
        else jsonl(rows_or_text)
    )
    return codex_transcript.transcript_from_bytes(
        SID, text.encode("utf-8")
    )


def problems_of(rows_or_text) -> str:
    with pytest.raises(TranscriptError) as caught:
        extract(rows_or_text)
    return "\n".join(caught.value.problems)


def test_extracts_normalized_messages_and_ignores_known_noise():
    rows = noise() + dialog(2) + noise()
    transcript = extract(rows)
    assert [
        (m.ordinal, m.role, m.text) for m in transcript.messages
    ] == [
        (1, "user", "Frage 0"),
        (2, "assistant", "Antwort 0"),
        (3, "user", "Frage 1"),
        (4, "assistant", "Antwort 1"),
    ]
    assert transcript.messages[0].source_line == 4
    assert transcript.agent == "codex"
    assert transcript.diagnostics == {
        "lines": len(rows),
        "user_messages": 2,
        "assistant_messages": 2,
    }


def test_digest_is_over_the_exact_bytes_and_messages_are_sorted():
    rows = [assistant(2), user(1)]
    data = jsonl(rows).encode("utf-8")
    transcript = codex_transcript.transcript_from_bytes(SID, data)
    assert transcript.source_digest == hashlib.sha256(data).hexdigest()
    assert [m.role for m in transcript.messages] == [
        "user",
        "assistant",
    ]
    assert transcript.messages[0].source_line == 2


def test_commentary_phase_is_filtered_but_known():
    rows = dialog(1) + [assistant(9, phase="commentary")]
    assert len(extract(rows).messages) == 2


def test_unknown_phase_is_reported_without_its_value():
    rows = dialog(1) + [assistant(9, phase=SECRET)]
    text = problems_of(rows)
    assert "T5" in text
    assert "payload.phase" in text
    assert "Zeile 3" in text
    assert SECRET not in text


def test_user_message_without_text_is_suspect():
    broken = user(1)
    broken["payload"]["item"]["content"] = [{"type": "image"}]
    text = problems_of([broken, assistant(2)])
    assert "T5" in text
    assert "payload.item.content" in text


def test_unknown_user_item_type_is_suspect_but_unrelated_item_is_not():
    other = user(1)
    other["payload"]["item"]["type"] = "UserAttachment"
    assert "payload.item.type" in problems_of([other, *dialog(1)])
    harmless = user(1)
    harmless["payload"]["item"]["type"] = "ToolCall"
    assert len(extract([harmless, *dialog(1)]).messages) == 2


def test_assistant_final_answer_without_output_text_is_suspect():
    broken = assistant(2)
    broken["payload"]["content"] = [{"type": "refusal"}]
    text = problems_of([user(1), broken])
    assert "T5" in text
    assert "payload.content" in text


def test_invalid_json_is_an_error_with_line_only():
    text = problems_of(jsonl(dialog(1)) + f"{{{SECRET}\n")
    assert "J1" in text
    assert "Zeile 3" in text
    assert SECRET not in text


def test_truncated_last_line_is_reported_as_possibly_incomplete():
    partial = json.dumps(dialog(1)[0])[:-5]
    text = problems_of(jsonl(dialog(1)) + partial)
    assert "J1" in text
    assert "unvollstaendig" in text


def test_valid_last_line_without_newline_is_accepted():
    data = jsonl(dialog(1)).rstrip("\n")
    assert len(extract(data).messages) == 2


def test_invalid_utf8_is_an_error_without_content():
    with pytest.raises(TranscriptError) as caught:
        codex_transcript.transcript_from_bytes(SID, b"\xff\xfe{}")
    assert "UTF-8" in str(caught.value)


def test_line_separator_inside_a_string_does_not_split_a_row():
    rows = [user(1, text="a b"), assistant(2)]
    assert extract(rows).messages[0].text == "a b"


@pytest.mark.parametrize(
    "ordinal",
    [None, True, "3", float("nan"), float("inf"), [1]],
)
def test_bad_ordinals_are_reported(ordinal):
    rows = [user(1), assistant(ordinal)]
    text = problems_of(jsonl(rows).replace("Infinity", "1e999"))
    assert "T3" in text
    assert "Zeile 2 ordinal" in text


def test_huge_integer_ordinals_are_valid_and_ordered_exactly():
    rows = [assistant(10**400 + 1), user(10**400)]
    messages = extract(rows).messages
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].ordinal == 10**400


def test_huge_duplicate_integer_ordinals_are_reported():
    assert "ordinal doppelt" in problems_of(
        [user(10**400), assistant(10**400)]
    )


def test_int_over_the_parser_digit_limit_is_invalid_json_not_a_crash():
    text = jsonl([user(1)]) + '{"ordinal": ' + "9" * 5000 + "}\n"
    assert "J1" in problems_of(text)


def test_missing_ordinal_key_is_reported():
    row = assistant(2)
    del row["ordinal"]
    assert "T3" in problems_of([user(1), row])


def test_duplicate_ordinals_are_reported_including_int_float_pairs():
    text = problems_of([user(1), assistant(1.0)])
    assert "ordinal doppelt" in text
    assert "Zeilen 1 und 2" in text


def test_float_ordinals_are_allowed():
    rows = [user(1.5), assistant(2.5)]
    assert [m.ordinal for m in extract(rows).messages] == [1.5, 2.5]


def test_t1_needs_both_roles():
    assert "T1" in problems_of([])
    assert "T1" in problems_of([user(1)])


def test_t2_counts_must_match():
    text = problems_of([user(1), assistant(2), user(3)])
    assert "T2" in text
    assert "user=2, assistant=1" in text


def test_t4_alternation_reports_the_first_break():
    rows = [user(1), user(2), assistant(3), assistant(4)]
    text = problems_of(rows)
    assert "T4" in text
    assert "Position 2, Zeile 2" in text


def test_t6_empty_text():
    text = problems_of([user(1, text="   "), assistant(2)])
    assert "T6" in text
    assert "Zeile 1" in text


def test_t7_turn_mismatch_only_when_both_present():
    assert "T7" in problems_of(
        [user(1, turn="a"), assistant(2, turn="b")]
    )
    no_turn = assistant(2, turn=None)
    assert len(extract([user(1, turn="a"), no_turn]).messages) == 2


def test_cases_are_capped_at_ten_and_the_rest_is_counted():
    rows = [user(1), assistant(2)] + [
        assistant(10 + i, phase=SECRET) for i in range(14)
    ]
    text = problems_of(rows)
    assert "T5" in text and "(14x)" in text
    assert text.count("payload.phase") == 10
    assert "4 weitere ausgelassen" in text
    assert SECRET not in text


def test_errors_carry_the_format_note_and_no_content():
    rows = [user(1, text=SECRET), user(2, text=SECRET)]
    text = problems_of(rows)
    assert "kein bewiesener CLI-Versionswechsel" in text
    assert SECRET not in text


def test_sentinel_stays_out_of_every_problem_string():
    rows = [
        user(1, text=SECRET),
        assistant(1, text=SECRET),
        user(3, text=" "),
    ]
    with pytest.raises(TranscriptError) as caught:
        extract(rows)
    assert SECRET not in "".join(caught.value.problems)
    assert SECRET not in repr(caught.value)


# --- Verzeichniskonfiguration und Suche ---


def test_sessions_dir_precedence():
    home = Path("/h")
    both = {
        "KI_DEV_CODEX_SESSIONS_DIR": "/explicit",
        "CODEX_HOME": "/ch",
    }
    assert resolve_codex_sessions_dir(both, home) == Path("/explicit")
    assert resolve_codex_sessions_dir(
        {"CODEX_HOME": "/ch"}, home
    ) == Path("/ch/sessions")
    assert resolve_codex_sessions_dir({}, home) == Path(
        "/h/.codex/sessions"
    )


@pytest.mark.parametrize(
    "environ",
    [
        {"KI_DEV_CODEX_SESSIONS_DIR": ""},
        {"KI_DEV_CODEX_SESSIONS_DIR": "  "},
        {"CODEX_HOME": ""},
        {"KI_DEV_CODEX_SESSIONS_DIR": "", "CODEX_HOME": "/ch"},
    ],
)
def test_empty_explicit_values_are_errors_not_fallbacks(environ):
    with pytest.raises(ValueError, match="leer"):
        resolve_codex_sessions_dir(environ, Path("/h"))


@pytest.mark.parametrize(
    "session_id",
    ["", "../x", "a/b", "a*", "a?", "a[1]", "a{b}", "-x", "a b", "a.b"],
)
def test_invalid_ids_are_request_errors(session_id):
    with pytest.raises(TranscriptRequestError):
        validate_session_request("codex", session_id)


def test_only_codex_is_a_transcript_provider():
    assert transcript_agents() == ("codex",)
    for agent in ("claude", "unbekannt", ""):
        with pytest.raises(TranscriptRequestError, match="nicht"):
            validate_session_request(agent, SID)


def test_find_session_rollout_requires_exactly_one_match(tmp_path):
    with pytest.raises(ValueError, match="fehlt"):
        find_session_rollout(tmp_path, SID)
    write_session(tmp_path, SID, dialog(1), day="2026/09/17")
    assert find_session_rollout(tmp_path, SID).name.endswith(
        f"{SID}.jsonl"
    )
    write_session(tmp_path, SID, dialog(1), day="2026/09/18")
    with pytest.raises(ValueError, match="mehrdeutig"):
        find_session_rollout(tmp_path, SID)


@pytest.fixture
def sessions_env(tmp_path, monkeypatch):
    monkeypatch.setenv("KI_DEV_CODEX_SESSIONS_DIR", str(tmp_path))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return tmp_path


def test_read_session_transcript_reads_the_configured_dir(sessions_env):
    write_session(sessions_env, SID, dialog(1))
    transcript = read_session_transcript("codex", SID)
    assert transcript.session_id == SID
    assert len(transcript.messages) == 2


def test_missing_session_never_falls_back_to_the_latest(sessions_env):
    write_session(sessions_env, "other-session", dialog(1))
    with pytest.raises(TranscriptError, match="nicht gefunden"):
        read_session_transcript("codex", SID)


def test_ambiguous_session_is_an_error(sessions_env):
    write_session(sessions_env, SID, dialog(1), day="2026/09/17")
    write_session(sessions_env, SID, dialog(1), day="2026/09/18")
    with pytest.raises(TranscriptError, match="mehrdeutig"):
        read_session_transcript("codex", SID)


def test_missing_sessions_dir_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "KI_DEV_CODEX_SESSIONS_DIR", str(tmp_path / "gibt-es-nicht")
    )
    with pytest.raises(TranscriptError, match="existiert nicht"):
        read_session_transcript("codex", SID)


def test_codex_home_and_home_are_used_when_no_explicit_dir(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("KI_DEV_CODEX_SESSIONS_DIR", raising=False)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    write_session(tmp_path / "sessions", SID, dialog(1))
    assert len(read_session_transcript("codex", SID).messages) == 2


def test_request_validation_does_not_touch_the_environment(monkeypatch):
    monkeypatch.setenv("KI_DEV_CODEX_SESSIONS_DIR", "")
    with pytest.raises(TranscriptRequestError):
        read_session_transcript("codex", "../x")


_JSON = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=8),
    lambda inner: (
        st.lists(inner, max_size=3)
        | st.dictionaries(st.text(max_size=6), inner, max_size=3)
    ),
    max_leaves=6,
)


@given(
    ordinal=_JSON,
    phase=_JSON,
    turn=_JSON,
    content=_JSON,
    item_type=_JSON,
    role=_JSON,
)
def test_arbitrary_field_values_never_crash_the_parser(
    ordinal, phase, turn, content, item_type, role
):
    user_row = user(1)
    user_row["payload"]["item"]["type"] = item_type
    user_row["payload"]["item"]["content"] = content
    user_row["payload"]["turn_id"] = turn
    assistant_row = assistant(ordinal, phase=phase)
    assistant_row["payload"]["role"] = role
    assistant_row["payload"]["content"] = content
    with contextlib.suppress(TranscriptError):
        extract([user_row, assistant_row])


def test_config_and_file_errors_become_transcript_errors(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KI_DEV_CODEX_SESSIONS_DIR", " ")
    with pytest.raises(TranscriptError, match="gesetzt, aber leer"):
        read_session_transcript("codex", SID)
    monkeypatch.setenv("KI_DEV_CODEX_SESSIONS_DIR", str(tmp_path))
    day = tmp_path / "2026" / "09" / "17"
    day.mkdir(parents=True)
    (day / f"rollout-x-{SID}.jsonl").mkdir()
    with pytest.raises(TranscriptError, match="IsADirectoryError"):
        read_session_transcript("codex", SID)
