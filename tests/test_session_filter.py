"""Automatische Herkunft erkennen; echte Sitzungen sichtbar halten."""

import json

import pytest

from ki_dev.session_filter import is_automatic_session
from tests import claude_session_fixtures as claude
from tests.codex_session_fixtures import session_meta, user

PROMPT = (
    "Bauauftrag fuer Lauf version-fix, Runde 1.\n"
    "Arbeitsverzeichnis: /tmp/tmp.example/app-work"
)


def classify(tmp_path, agent, rows, exclude=()):
    path = tmp_path / "session.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return is_automatic_session(agent, path, exclude)


@pytest.mark.parametrize("agent", ["codex", "claude"])
@pytest.mark.parametrize("review", [False, True])
def test_generated_prompt_is_recognized_in_both_providers(
    tmp_path, agent, review
):
    prompt = (
        PROMPT.replace("Bauauftrag", "Unabhaengiger Review")
        if review
        else PROMPT
    )
    row = (
        user(1, text=prompt)
        if agent == "codex"
        else claude.human(prompt)
    )
    assert classify(tmp_path, agent, [row])


@pytest.mark.parametrize(
    "cwd",
    [
        "/tmp/pytest-of-agent/pytest-1/repo",
        "/workspace/.local/var/readme-check/run-1/app",
        "/workspace/.local/var/readme-walkthrough/run-1/app",
    ],
)
def test_known_test_directories_are_excluded(tmp_path, cwd):
    meta = session_meta("id")
    meta["payload"]["cwd"] = cwd
    assert classify(tmp_path, "codex", [meta, user(1)])


def test_subagents_are_recognized_by_metadata(tmp_path):
    meta = session_meta("id")
    meta["payload"]["source"] = {"subagent": {"other": "guardian"}}
    assert classify(tmp_path, "codex", [meta])


def test_exec_and_temp_directory_are_not_sufficient(tmp_path):
    meta = session_meta("id")
    meta["payload"].update(
        source="exec", cwd="/tmp/tmp.example/app-work"
    )
    assert not classify(tmp_path, "codex", [meta, user(1)])


def test_a_later_generated_prompt_does_not_hide_a_human_session(
    tmp_path,
):
    assert not classify(
        tmp_path, "codex", [user(1), user(2, text=PROMPT)]
    )


@pytest.mark.parametrize("content", ["{broken", "[]", "null", ""])
def test_unknown_and_damaged_records_remain_visible(tmp_path, content):
    path = tmp_path / "broken.jsonl"
    path.write_text(content)
    assert not is_automatic_session("codex", path, ())


def test_unreadable_source_remains_for_transcript_diagnostics(tmp_path):
    assert not is_automatic_session("claude", tmp_path / "missing", ())
