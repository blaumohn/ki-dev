import json

import pytest
from typer.testing import CliRunner

from ki_dev.cli import app
from tests import claude_session_fixtures as claude
from tests.codex_session_fixtures import (
    SECRET,
    dialog,
    session_meta,
    user,
    write_session,
)

runner = CliRunner()
SID = "0199aaaa-bbbb-cccc-dddd-eeeeffff0001"
TRANSCRIPT = ["session", "transcript", SID, "--agent", "codex"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.setenv("KI_DEV_CODEX_SESSIONS_DIR", str(sessions))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.chdir(work)
    env.sessions, env.work = sessions, work
    return env


def codex_session(env, rows=None):
    rows = [session_meta(SID), *(rows or dialog(2))]
    return write_session(env.sessions, SID, rows)


def stored(env):
    return sorted((env.work / ".local/var/transcripts").glob("*.jsonl"))


def test_transcript_writes_a_dated_snapshot_and_prints_its_path(env):
    codex_session(env, [user(1, "t0", SECRET), *dialog(1)[1:]])
    result = runner.invoke(app, [*TRANSCRIPT, "--title", "Ausgabe"])
    assert result.exit_code == 0, result.stderr
    [path] = stored(env)
    assert path.name == "260917T09_ausgabe_0199aaaa.jsonl"
    assert result.stdout.strip() == (
        ".local/var/transcripts/260917T09_ausgabe_0199aaaa.jsonl"
    )
    assert SECRET not in result.stdout + result.stderr
    header = json.loads(path.read_text().splitlines()[0])
    assert header["title"] == "Ausgabe"


def test_repeat_reuses_and_new_state_adds_a_file(env):
    path = codex_session(env)
    first = runner.invoke(app, [*TRANSCRIPT, "--title", "A"])
    again = runner.invoke(app, [*TRANSCRIPT, "--title", "A"])
    assert first.stdout == again.stdout
    path.write_text(path.read_text() + "\n")
    newer = runner.invoke(app, [*TRANSCRIPT, "--title", "A"])
    assert newer.exit_code == 0, newer.stderr
    assert len(stored(env)) == 2


def test_dir_option_selects_the_target(env):
    codex_session(env)
    target = env.work / "anders"
    result = runner.invoke(
        app, [*TRANSCRIPT, "--title", "A", "--dir", str(target)]
    )
    assert result.exit_code == 0, result.stderr
    assert len(list(target.glob("*.jsonl"))) == 1
    assert stored(env) == []


def test_claude_session_uses_the_same_contract(env, monkeypatch):
    root = env.sessions.parent / "claude-projects"
    monkeypatch.setenv("KI_DEV_CLAUDE_SESSIONS_DIR", str(root))
    claude.write_session(
        root, claude.SESSION, claude.chain(claude.dialog())
    )
    result = runner.invoke(
        app,
        [
            "session",
            "transcript",
            claude.SESSION,
            "--agent",
            "claude",
            "--title",
            "Claude",
        ],
    )
    assert result.exit_code == 0, result.stderr
    [path] = stored(env)
    assert json.loads(path.read_text().splitlines()[0])["agent"] == (
        "claude"
    )


@pytest.mark.parametrize(
    "args",
    [
        TRANSCRIPT,
        [*TRANSCRIPT, "--title", " "],
        [*TRANSCRIPT, "--title", "!!!"],
        [
            "session",
            "transcript",
            "../x",
            "--agent",
            "codex",
            "--title",
            "A",
        ],
        [
            "session",
            "transcript",
            SID,
            "--agent",
            "gemini",
            "--title",
            "A",
        ],
    ],
)
def test_bad_calls_exit_2_without_effect(env, args):
    codex_session(env)
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert stored(env) == []


def test_session_without_start_exits_1_without_file(env):
    write_session(env.sessions, SID, dialog(1))
    result = runner.invoke(app, [*TRANSCRIPT, "--title", "A"])
    assert result.exit_code == 1
    assert "started_at fehlt" in result.stderr
    assert stored(env) == []


def test_invalid_session_exits_1_without_content(env):
    codex_session(env, [user(1, text=SECRET), user(1, text=SECRET)])
    result = runner.invoke(app, [*TRANSCRIPT, "--title", "A"])
    assert result.exit_code == 1
    assert "Sitzung nicht verwendbar" in result.stderr
    assert SECRET not in result.stdout + result.stderr
    assert stored(env) == []
