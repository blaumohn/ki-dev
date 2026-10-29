import hashlib
import json
from pathlib import Path

import pytest

from ki_dev.adapter.executors import claude_transcript
from ki_dev.adapter.executors.claude_sessions import (
    find_claude_sessions,
    resolve_claude_sessions_dir,
)
from ki_dev.adapter.executors.session_transcript import (
    TranscriptError,
    TranscriptRequestError,
    require_started_at,
)
from ki_dev.adapter.executors.transcript import (
    read_session_transcript,
    validate_session_request,
)
from tests.claude_session_fixtures import (
    SESSION,
    chain,
    compact_summary,
    dialog,
    human,
    interruption,
    jsonl,
    local_command,
    reply,
    task_notification,
    tool_result,
    write_session,
)
from tests.codex_session_fixtures import SECRET


def extract(rows_or_text):
    text = (
        rows_or_text
        if isinstance(rows_or_text, str)
        else jsonl(rows_or_text)
    )
    return claude_transcript.transcript_from_bytes(
        SESSION, text.encode("utf-8")
    )


def problems_of(rows_or_text) -> str:
    with pytest.raises(TranscriptError) as caught:
        extract(rows_or_text)
    return "\n".join(caught.value.problems)


def test_extracts_human_inputs_and_final_texts_without_ordinals():
    transcript = extract(dialog(2))
    assert [
        (m.position, m.ordinal, m.role, m.text, m.source_line)
        for m in transcript.messages
    ] == [
        (1, None, "user", "Frage 0", 1),
        (2, None, "assistant", "Antwort 0", 2),
        (3, None, "user", "Frage 1", 3),
        (4, None, "assistant", "Antwort 1", 4),
    ]
    assert transcript.agent == "claude"
    assert (
        transcript.messages[0].timestamp == "2026-10-05T10:00:01.000Z"
    )


def test_session_times_come_from_the_session_records():
    transcript = extract(dialog(2))
    assert transcript.started_at == "2026-10-05T10:00:01.000Z"
    assert transcript.last_activity_at == "2026-10-05T10:00:04.000Z"
    assert require_started_at(transcript).year == 2026


def test_digest_is_over_the_exact_bytes():
    data = jsonl(dialog(1)).encode("utf-8")
    transcript = claude_transcript.transcript_from_bytes(SESSION, data)
    assert transcript.source_digest == hashlib.sha256(data).hexdigest()


def test_repeated_roles_and_open_input_are_kept_and_counted():
    rows = chain(
        [human("a"), human("b"), reply("c"), reply("d"), human("e")]
    )
    transcript = extract(rows)
    assert [m.role for m in transcript.messages] == [
        "user",
        "user",
        "assistant",
        "assistant",
        "user",
    ]
    diagnostics = transcript.diagnostics
    assert (
        diagnostics["human_inputs_without_final_before_next_input"] == 1
    )
    assert diagnostics["human_input_pending_at_eof"] == 1
    assert diagnostics["T2_count_mismatch"] == 1
    assert diagnostics["T4_role_breaks"] > 0


def test_tool_use_texts_are_commentary_counted_not_kept():
    rows = chain(
        [human(), reply("zwischen", stop_reason="tool_use"), reply()]
    )
    transcript = extract(rows)
    assert [m.text for m in transcript.messages] == ["Frage", "Antwort"]
    assert transcript.diagnostics["commentary_text_records"] == 1


def test_proven_task_notification_is_excluded_and_counted():
    rows = chain([human(), task_notification(SECRET), reply()])
    transcript = extract(rows)
    assert len(transcript.messages) == 2
    assert transcript.diagnostics["task_notifications_excluded"] == 1


def test_compact_summary_is_excluded_and_counted():
    rows = chain(
        [human(), reply(), compact_summary(SECRET), human(), reply()]
    )
    transcript = extract(rows)
    assert [m.text for m in transcript.messages] == [
        "Frage",
        "Antwort",
        "Frage",
        "Antwort",
    ]
    assert transcript.diagnostics["compact_summaries_excluded"] == 1


@pytest.mark.parametrize(
    "override",
    [
        {"isCompactSummary": False},
        {"isVisibleInTranscriptOnly": False},
        {"origin": {"kind": "human"}},
        {"turnOrigin": "human"},
        {"promptSource": "typed"},
    ],
)
def test_compact_summary_needs_both_marks_and_no_origin(override):
    entry = compact_summary(SECRET) | override
    text = problems_of(chain([human(), reply(), entry, reply()]))
    assert "Zeile 3" in text
    assert SECRET not in text


@pytest.mark.parametrize(
    "quoted",
    [
        "<command-name>/model</command-name> warum passiert das?",
        "<local-command-stdout>Fehler</local-command-stdout> hilf",
    ],
)
def test_human_quote_of_a_command_tag_is_kept(quoted):
    transcript = extract(chain([human(quoted), reply()]))
    assert [m.text for m in transcript.messages] == [quoted, "Antwort"]
    assert "local_commands_excluded" not in transcript.diagnostics


def test_unmarked_local_command_lines_are_excluded_and_counted():
    rows = chain(
        [
            local_command(),
            local_command(
                "<local-command-stdout>ok</local-command-stdout>"
            ),
            human(),
            reply(),
        ]
    )
    transcript = extract(rows)
    assert [m.text for m in transcript.messages] == ["Frage", "Antwort"]
    assert transcript.diagnostics["local_commands_excluded"] == 2


@pytest.mark.parametrize(
    "text",
    [
        "[Request interrupted by user]",
        "[Request interrupted by user for tool use]",
    ],
)
def test_unmarked_interruption_markers_are_excluded_and_counted(text):
    rows = chain(
        [human(), interruption(text), human("Weiter"), reply()]
    )
    transcript = extract(rows)
    assert [m.text for m in transcript.messages] == [
        "Frage",
        "Weiter",
        "Antwort",
    ]
    assert transcript.diagnostics["interruption_markers"] == 1


def test_interruption_text_with_origin_or_other_text_is_not_excluded():
    quoted = interruption() | {"promptSource": "system"}
    other = interruption("[Request interrupted by someone]")
    for entry in (quoted, other):
        text = problems_of(chain([human(), entry, reply()]))
        assert "ohne belegte menschliche Herkunft" in text


def test_command_tag_with_foreign_origin_is_an_error_not_excluded():
    entry = local_command() | {"promptSource": "system"}
    text = problems_of(chain([entry, human(), reply()]))
    assert "Zeile 1" in text
    assert "ohne belegte menschliche Herkunft" in text
    assert "content=str<command-name>" in text


def test_human_quote_of_a_notification_tag_is_kept():
    quoted = (
        "<task-notification>zitiert</task-notification> bitte prüfen"
    )
    transcript = extract(chain([human(quoted), reply()]))
    assert transcript.messages[0].text == quoted
    assert "task_notifications_excluded" not in transcript.diagnostics


@pytest.mark.parametrize(
    "override",
    [
        {"promptSource": "typed"},
        {"turnOrigin": "human"},
        {"origin": {"kind": "human"}},
    ],
)
def test_contradictory_notification_origin_is_an_error(override):
    entry = task_notification(SECRET) | override
    text = problems_of(chain([human(), entry, reply()]))
    assert "Zeile 2" in text
    assert SECRET not in text


def test_unknown_human_origin_values_never_leak_into_diagnostics():
    entry = human(SECRET, promptSource=SECRET, turnOrigin=SECRET)
    entry["origin"] = {"kind": "human"}
    text = problems_of(chain([entry, reply()]))
    assert "unbekannte menschliche Herkunftsmarkierung" in text
    assert "promptSource=<str>" in text
    assert SECRET not in text


def test_user_entry_without_origin_is_an_error():
    entry = {
        "type": "user",
        "message": {"role": "user", "content": SECRET},
    }
    text = problems_of(chain([entry, reply()]))
    assert "ohne belegte menschliche Herkunft" in text
    assert SECRET not in text


def test_tool_results_are_excluded():
    transcript = extract(chain([human(), tool_result(), reply()]))
    assert transcript.diagnostics["tool_results_excluded"] == 1


def test_invalid_json_is_an_error_with_line_only():
    text = problems_of(jsonl(dialog(1)) + f"{{{SECRET}\n")
    assert "Zeile 3: ungueltiges JSON" in text
    assert SECRET not in text


def test_invalid_field_names_path_and_rule_only():
    rows = dialog(1)
    rows[1]["message"]["stop_reason"] = 7
    text = problems_of(rows)
    assert "message.stop_reason (type)" in text


def test_missing_field_is_named():
    rows = dialog(1)
    del rows[0]["sessionId"]
    assert "fehlt: sessionId" in problems_of(rows)


def test_missing_timestamps_stay_missing():
    rows = dialog(1)
    for row in rows:
        del row["timestamp"]
    transcript = extract(rows)
    assert [m.timestamp for m in transcript.messages] == [None, None]
    assert transcript.started_at is None
    assert transcript.last_activity_at is None
    assert transcript.diagnostics["records_without_timestamp"] == 2
    with pytest.raises(TranscriptError, match="started_at fehlt"):
        require_started_at(transcript)


def test_partly_missing_timestamps_use_only_present_values():
    rows = dialog(2)
    del rows[0]["timestamp"]
    del rows[3]["timestamp"]
    transcript = extract(rows)
    assert transcript.messages[0].timestamp is None
    assert transcript.started_at == "2026-10-05T10:00:02.000Z"
    assert transcript.last_activity_at == "2026-10-05T10:00:03.000Z"


def test_invalid_timestamp_is_an_error_not_missing():
    rows = dialog(1)
    rows[1]["timestamp"] = SECRET
    text = problems_of(rows)
    assert "Zeile 2" in text and "timestamp" in text
    assert SECRET not in text


def test_empty_transcript_is_an_error():
    assert "keine Transkriptbeitraege" in problems_of(
        chain([tool_result()])
    )
    assert "keine Transkriptbeitraege" in problems_of("")


def test_broken_lineage_and_mixed_sessions_are_errors():
    rows = dialog(1)
    rows[1]["parentUuid"] = "unbekannt"
    assert "parentUuid" in problems_of(rows)
    rows = dialog(1)
    rows[1]["sessionId"] = "andere"
    assert "sessionId passt nicht" in problems_of(rows)


def test_session_must_match_the_requested_id():
    rows = dialog(1)
    for row in rows:
        row["sessionId"] = SECRET
    text = problems_of(rows)
    assert "Zeile 1: sessionId passt nicht" in text
    assert SECRET not in text
    assert len(extract(dialog(1)).messages) == 2


def test_unknown_stop_reason_is_an_error_without_value():
    rows = chain([human(), reply(stop_reason=SECRET)])
    text = problems_of(rows)
    assert "stop_reason=<str>" in text
    assert SECRET not in text


def test_sentinel_stays_out_of_every_problem_string():
    cases = [
        chain([human(SECRET, promptSource=SECRET), reply(SECRET)]),
        chain([human(), reply(SECRET, stop_reason=SECRET)]),
        jsonl(dialog(1)) + SECRET,
    ]
    for case in cases:
        with pytest.raises(TranscriptError) as caught:
            extract(case)
        assert SECRET not in "".join(caught.value.problems)
        assert SECRET not in repr(caught.value)


# --- Verzeichniskonfiguration, Suche und Digest-Konsistenz ---


def test_sessions_dir_precedence():
    home = Path("/h")
    explicit = {"KI_DEV_CLAUDE_SESSIONS_DIR": "/projekte"}
    assert resolve_claude_sessions_dir(explicit, home) == Path(
        "/projekte"
    )
    assert resolve_claude_sessions_dir({}, home) == Path(
        "/h/.claude/projects"
    )


@pytest.mark.parametrize("value", ["", "  "])
def test_empty_explicit_value_is_an_error_not_a_fallback(value):
    with pytest.raises(ValueError, match="gesetzt, aber leer"):
        resolve_claude_sessions_dir(
            {"KI_DEV_CLAUDE_SESSIONS_DIR": value}, Path("/h")
        )


@pytest.mark.parametrize("session_id", ["", "../x", "a/b", "a*", "a.b"])
def test_invalid_ids_are_request_errors(session_id):
    with pytest.raises(TranscriptRequestError):
        validate_session_request("claude", session_id)


@pytest.fixture
def sessions_env(tmp_path, monkeypatch):
    monkeypatch.setenv("KI_DEV_CLAUDE_SESSIONS_DIR", str(tmp_path))
    return tmp_path


def test_read_session_transcript_reads_the_configured_dir(sessions_env):
    write_session(sessions_env, SESSION, dialog(1))
    transcript = read_session_transcript("claude", SESSION)
    assert transcript.session_id == SESSION
    assert len(transcript.messages) == 2


def test_default_dir_is_home_claude_projects(tmp_path, monkeypatch):
    monkeypatch.delenv("KI_DEV_CLAUDE_SESSIONS_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    write_session(tmp_path / ".claude" / "projects", SESSION, dialog(1))
    assert len(read_session_transcript("claude", SESSION).messages) == 2


def test_missing_and_ambiguous_sessions_are_errors(sessions_env):
    with pytest.raises(TranscriptError, match="nicht gefunden"):
        read_session_transcript("claude", SESSION)
    write_session(sessions_env, SESSION, dialog(1), project="a")
    write_session(sessions_env, SESSION, dialog(1), project="b")
    assert len(find_claude_sessions(sessions_env, SESSION)) == 2
    with pytest.raises(TranscriptError, match="mehrdeutig"):
        read_session_transcript("claude", SESSION)


def test_config_errors_become_clean_transcript_errors(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KI_DEV_CLAUDE_SESSIONS_DIR", "")
    with pytest.raises(TranscriptError, match="gesetzt, aber leer"):
        read_session_transcript("claude", SESSION)
    monkeypatch.setenv(
        "KI_DEV_CLAUDE_SESSIONS_DIR", str(tmp_path / "x")
    )
    with pytest.raises(TranscriptError, match="existiert nicht"):
        read_session_transcript("claude", SESSION)


def test_growing_session_is_read_as_one_consistent_state(sessions_env):
    path = write_session(sessions_env, SESSION, dialog(1))
    first = read_session_transcript("claude", SESSION)
    first_bytes = path.read_bytes()
    more = chain([human("nach"), reply("trag")], start_second=10)
    more[0]["uuid"], more[0]["parentUuid"] = "u9", "u2"
    more[1]["uuid"], more[1]["parentUuid"] = "u10", "u9"
    path.write_text(path.read_text() + jsonl(more))
    second = read_session_transcript("claude", SESSION)
    assert (
        first.source_digest == hashlib.sha256(first_bytes).hexdigest()
    )
    assert (
        second.source_digest
        == hashlib.sha256(path.read_bytes()).hexdigest()
    )
    assert (len(first.messages), len(second.messages)) == (2, 4)
    path.write_text(path.read_text() + json.dumps(human())[:-4])
    with pytest.raises(TranscriptError, match="evtl. unvollstaendig"):
        read_session_transcript("claude", SESSION)
