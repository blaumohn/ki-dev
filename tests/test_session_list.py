import os

import pytest
from typer.testing import CliRunner

from ki_dev import session_list
from ki_dev.cli import app
from tests import claude_session_fixtures as claude
from tests.codex_session_fixtures import (
    SECRET,
    assistant,
    session_meta,
    user,
    write_session,
)

runner = CliRunner()
CODEX_ID = "0199aaaa-bbbb-cccc-dddd-eeeeffff0001"
OLDER_ID = "0199aaaa-bbbb-cccc-dddd-eeeeffff0003"
CLAUDE_ID = claude.SESSION


def at(path, second):
    os.utime(path, (second, second))
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    codex = tmp_path / "codex"
    projects = tmp_path / "projects"
    codex.mkdir()
    projects.mkdir()
    monkeypatch.setenv("KI_DEV_CODEX_SESSIONS_DIR", str(codex))
    monkeypatch.setenv("KI_DEV_CLAUDE_SESSIONS_DIR", str(projects))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    env.codex, env.projects = codex, projects
    return env


def codex_session(env, session_id, first, answer, second):
    rows = [
        session_meta(session_id),
        user(1, "t0", first),
        assistant(2, "t0", answer),
    ]
    return at(write_session(env.codex, session_id, rows), second)


def claude_session(env, text, second):
    rows = claude.chain([claude.human(text), claude.reply("Antwort C")])
    path = claude.write_session(env.projects, CLAUDE_ID, rows)
    return at(path, second)


def rows_of(result):
    return [line for line in result.stdout.splitlines() if line.strip()]


def test_list_merges_agents_newest_first_with_numbers_and_ids(env):
    codex_session(env, OLDER_ID, "Alt", "Antwort alt", 100)
    codex_session(env, CODEX_ID, "Frage X", "Antwort X", 300)
    claude_session(env, "Frage C", 200)
    result = runner.invoke(app, ["session", "list"])
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    assert (
        out.index(CODEX_ID) < out.index(CLAUDE_ID) < out.index(OLDER_ID)
    )
    assert "Mensch: Frage X" in out
    assert "Agent: Antwort X" in out
    assert "Mensch: Frage C" in out
    assert "codex · 20" in out and "claude · 20" in out
    numbers = [line.split()[0] for line in out.splitlines()[2:]]
    assert [n for n in numbers if n.isdigit()] == ["1", "2", "3"]


def test_count_argument_limits_the_list(env):
    codex_session(env, OLDER_ID, "Alt", "Antwort alt", 100)
    codex_session(env, CODEX_ID, "Neu", "Antwort neu", 300)
    result = runner.invoke(app, ["session", "list", "1"])
    assert result.exit_code == 0, result.stderr
    assert CODEX_ID in result.stdout
    assert OLDER_ID not in result.stdout


def test_list_and_number_only_filter_until_enough_matches(
    env, monkeypatch
):
    old = codex_session(env, OLDER_ID, "Alt", "Antwort", 100)
    newest = codex_session(env, CODEX_ID, "Neu", "Antwort", 200)
    automatic = claude_session(
        env,
        "Bauauftrag fuer Lauf test, Runde 1.\n"
        "Arbeitsverzeichnis: /work",
        300,
    )
    actual_filter = session_list.is_automatic_session
    examined = []

    def track(agent, path, exclude_cwd):
        examined.append(path)
        return actual_filter(agent, path, exclude_cwd)

    monkeypatch.setattr(session_list, "is_automatic_session", track)
    for args in (["list", "1"], ["show", "-n", "1"]):
        examined.clear()
        result = runner.invoke(app, ["session", *args])
        assert result.exit_code == 0, result.stderr
        assert CODEX_ID in result.stdout
        assert examined == [automatic, newest]
        assert old not in examined


def test_automatic_sessions_are_filtered_before_limit_and_number(env):
    codex_session(env, OLDER_ID, "Echte Frage", "Antwort", 100)
    prompt = (
        "Bauauftrag fuer Lauf version-fix, Runde 1.\n"
        "Arbeitsverzeichnis: /tmp/tmp.example/app-work\nAuftrag"
    )
    codex_session(env, CODEX_ID, prompt, "Fertig", 300)
    # Codex legt vor dem belegten UserMessage Umgebung und Anweisungen
    # ebenfalls als response_item mit role=user ab: kein Menschbeitrag.
    generated = [
        session_meta(CODEX_ID),
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "<environment_context>",
                    }
                ],
            },
        },
        user(1, "t0", prompt),
        assistant(2, "t0", "Fertig"),
    ]
    at(write_session(env.codex, CODEX_ID, generated), 300)
    sdk = claude.human(prompt, turnOrigin="sdk", promptSource="sdk")
    sdk.pop("origin")
    path = claude.write_session(
        env.projects,
        CLAUDE_ID,
        claude.chain([sdk, claude.reply()]),
    )
    at(path, 400)
    result = runner.invoke(app, ["session", "list", "1"])
    assert result.exit_code == 0, result.stderr
    assert OLDER_ID in result.stdout
    assert CODEX_ID not in result.stdout
    assert CLAUDE_ID not in result.stdout
    shown = runner.invoke(app, ["session", "show", "-n", "1"])
    assert shown.exit_code == 0, shown.stderr
    assert "Echte Frage" in shown.stdout
    exported = runner.invoke(
        app, ["session", "export", "-n", "1", "--format", "jsonl"]
    )
    assert exported.exit_code == 0, exported.stderr
    assert OLDER_ID in exported.stdout
    all_rows = runner.invoke(
        app, ["session", "list", "3", "--include-tests"]
    )
    assert CODEX_ID in all_rows.stdout
    assert CLAUDE_ID in all_rows.stdout
    assert "nicht verwendbar" in all_rows.stdout
    selected = runner.invoke(
        app, ["session", "show", "-n", "2", "--include-tests"]
    )
    assert selected.exit_code == 0, selected.stderr
    assert CODEX_ID in selected.stdout
    explicit = runner.invoke(
        app, ["session", "show", CODEX_ID, "--agent", "codex"]
    )
    assert explicit.exit_code == 0, explicit.stderr


def test_sdk_origin_alone_does_not_hide_unusable_sessions(env):
    sdk = claude.human("Frage", turnOrigin="sdk", promptSource="sdk")
    sdk.pop("origin")
    claude.write_session(
        env.projects, CLAUDE_ID, claude.chain([sdk, claude.reply()])
    )
    result = runner.invoke(app, ["session", "list"])
    assert CLAUDE_ID in result.stdout
    assert "nicht verwendbar" in result.stdout


def test_agent_filters_the_list(env):
    codex_session(env, CODEX_ID, "Frage X", "Antwort X", 300)
    claude_session(env, "Frage C", 400)
    result = runner.invoke(app, ["session", "list", "--agent", "codex"])
    assert result.exit_code == 0, result.stderr
    assert CODEX_ID in result.stdout
    assert CLAUDE_ID not in result.stdout


def test_preview_is_one_short_line_per_role(env):
    long_text = "wort " * 40
    first = f"Zeile eins\n\n  Zeile zwei {long_text}"
    codex_session(env, CODEX_ID, first, "ok", 1)
    result = runner.invoke(app, ["session", "list"])
    flat = " ".join(result.stdout.split())
    assert "Mensch: Zeile eins Zeile zwei wort" in flat
    assert flat.count("wort") < 20
    assert "…" in flat


def test_unusable_session_is_marked_without_content(env):
    path = codex_session(env, CODEX_ID, SECRET, "Antwort", 100)
    path.write_text(path.read_text() + "{kaputt " + SECRET + "\n")
    codex_session(env, OLDER_ID, "Gut", "Antwort", 50)
    result = runner.invoke(app, ["session", "list"])
    assert result.exit_code == 0, result.stderr
    assert "nicht verwendbar" in result.stdout
    assert "Mensch: Gut" in result.stdout
    assert SECRET not in result.stdout + result.stderr


def test_subagent_and_foreign_files_are_not_sessions(env):
    claude_session(env, "Frage C", 100)
    nested = env.projects / "-workspace" / CLAUDE_ID / "subagents"
    nested.mkdir(parents=True)
    (nested / "agent-1.jsonl").write_text("{}\n")
    (env.projects / "-workspace" / "notizen.txt").write_text("x")
    (env.codex / "2026/09/17").mkdir(parents=True)
    (env.codex / "2026/09/17/anderes.jsonl").write_text("{}\n")
    result = runner.invoke(app, ["session", "list"])
    assert result.exit_code == 0, result.stderr
    assert result.stdout.count("\n") == 4
    assert "agent-1" not in result.stdout


def test_missing_default_folder_is_a_hint_not_an_error(env):
    claude_session(env, "Frage C", 100)
    env.codex.rmdir()
    result = runner.invoke(app, ["session", "list"])
    assert result.exit_code == 0, result.stderr
    assert CLAUDE_ID in result.stdout
    assert "kein Sitzungsordner für codex" in result.stderr


def test_missing_folder_of_requested_agent_is_an_error(env):
    env.codex.rmdir()
    result = runner.invoke(app, ["session", "list", "--agent", "codex"])
    assert result.exit_code == 1
    assert "Sitzungsordner für codex fehlt" in result.stderr


def test_empty_folder_variable_is_an_error(env, monkeypatch):
    monkeypatch.setenv("KI_DEV_CODEX_SESSIONS_DIR", " ")
    result = runner.invoke(app, ["session", "list"])
    assert result.exit_code == 1
    assert "KI_DEV_CODEX_SESSIONS_DIR ist gesetzt, aber leer" in (
        result.stderr
    )


def test_no_sessions_is_reported_on_stderr(env):
    result = runner.invoke(app, ["session", "list"])
    assert result.exit_code == 0
    assert result.stdout == ""
    assert "Keine Sitzungen gefunden" in result.stderr


@pytest.mark.parametrize(
    "args",
    [["list", "0"], ["list", "--agent", "gemini"], ["show", "-n", "0"]],
)
def test_bad_call_is_a_usage_error(env, args):
    result = runner.invoke(app, ["session", *args])
    assert result.exit_code == 2


def test_show_by_number_picks_that_entry_of_the_list(env):
    codex_session(env, CODEX_ID, "Frage X", "Antwort X", 300)
    claude_session(env, "Frage C", 200)
    second = runner.invoke(app, ["session", "show", "-n", "2"])
    assert second.exit_code == 0, second.stderr
    assert "Frage C" in second.stdout
    assert "Frage X" not in second.stdout
    first = runner.invoke(
        app, ["session", "show", "-n", "1", "--agent", "codex"]
    )
    assert "Frage X" in first.stdout


def test_export_by_number_prints_markdown(env):
    codex_session(env, CODEX_ID, "Frage X", "Antwort X", 300)
    result = runner.invoke(
        app, ["session", "export", "-n", "1", "--format", "markdown"]
    )
    assert result.exit_code == 0, result.stderr
    assert "Frage X" in result.stdout


def test_number_beyond_the_list_is_an_error(env):
    codex_session(env, CODEX_ID, "Frage X", "Antwort X", 300)
    result = runner.invoke(app, ["session", "show", "-n", "2"])
    assert result.exit_code == 1
    assert "Nummer 2 nicht vorhanden (1 Sitzungen)" in result.stderr


def test_number_does_not_mix_with_id_or_snapshot(env):
    result = runner.invoke(
        app, ["session", "show", CODEX_ID, "-n", "1"]
    )
    assert result.exit_code == 2
    assert "nicht mit SESSION_ID" in result.stderr
