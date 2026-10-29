"""Inhaltsfilter und sichere Diagnosen des Claude-Transkriptparsers."""

import pytest

from tests.claude_session_fixtures import (
    chain,
    compact_summary,
    dialog,
    extract,
    human,
    interruption,
    local_command,
    problems_of,
    reply,
    task_notification,
    tool_result,
)
from tests.codex_session_fixtures import SECRET


def test_tool_use_texts_are_commentary_counted_not_kept():
    rows = chain(
        [human(), reply("zwischen", stop_reason="tool_use"), reply()]
    )
    transcript = extract(rows)
    assert [m.text for m in transcript.messages] == ["Frage", "Antwort"]
    assert transcript.diagnostics["commentary_text_records"] == 1


def test_null_stop_reason_before_interruption_is_counted_not_kept():
    rows = chain(
        [
            human(),
            reply(SECRET, stop_reason=None),
            interruption(),
            human("Weiter"),
            reply(),
        ]
    )
    transcript = extract(rows)
    assert [m.text for m in transcript.messages] == [
        "Frage",
        "Weiter",
        "Antwort",
    ]
    assert transcript.diagnostics["commentary_text_records"] == 1
    assert transcript.diagnostics["interruption_markers"] == 1
    assert (
        transcript.diagnostics[
            "human_inputs_without_final_before_next_input"
        ] == 1
    )
    assert transcript.diagnostics["human_input_pending_at_eof"] == 0


@pytest.mark.parametrize("completed", [False, True])
def test_null_stop_reason_leaves_input_pending_until_final(completed):
    entries = [human(), reply(SECRET, stop_reason=None)]
    if completed:
        entries.append(reply())
    transcript = extract(chain(entries))
    assert [m.text for m in transcript.messages] == (
        ["Frage", "Antwort"] if completed else ["Frage"]
    )
    assert transcript.diagnostics["commentary_text_records"] == 1
    assert transcript.diagnostics["human_input_pending_at_eof"] == int(
        not completed
    )


def test_missing_stop_reason_is_still_an_error():
    rows = dialog(1)
    del rows[1]["message"]["stop_reason"]
    text = problems_of(rows)
    assert "Zeile 2" in text
    assert "message.stop_reason" in text
    assert "stop_reason=<fehlt>" in text


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


def test_unknown_stop_reason_is_an_error_without_value():
    rows = chain([human(), reply(stop_reason=SECRET)])
    text = problems_of(rows)
    assert "message.stop_reason" in text
    assert "stop_reason=<str>" in text
    assert SECRET not in text
