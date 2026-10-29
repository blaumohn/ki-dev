import json
import os

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
        ["session", "transcript"],
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


# --- show / export (70u.4) -------------------------------------------

SHOW = ["session", "show", SID, "--agent", "codex"]
EXPORT = ["session", "export", SID, "--agent", "codex"]


def snapshot_file(env, title="Gespeichert"):
    codex_session(env)
    result = runner.invoke(app, [*TRANSCRIPT, "--title", title])
    assert result.exit_code == 0, result.stderr
    return stored(env)[0]


def all_files(env):
    return sorted(p for p in env.work.rglob("*") if p.is_file())


def test_show_renders_metadata_once_then_roles_and_markdown(env):
    codex_session(env, [user(1, "t0", "**fett**"), *dialog(1)[1:]])
    result = runner.invoke(app, SHOW)
    assert result.exit_code == 0, result.stderr
    out = result.stdout
    assert out.count(SID) == 2  # Titelersatz und Metadatenzeile
    assert out.count("Beginn 2026-09-17T09:10:35Z") == 1
    assert "1 Mensch" in out and "2 Agent" in out
    assert "fett" in out and "**fett**" not in out
    assert "transcript_meta" not in out
    assert "\x1b[" not in out
    assert result.stderr == ""
    assert all_files(env) == []


def test_show_snapshot_uses_the_stored_title_and_same_messages(env):
    path = snapshot_file(env)
    raw = runner.invoke(app, SHOW).stdout
    from_snapshot = runner.invoke(
        app, ["session", "show", "--snapshot", str(path)]
    )
    assert from_snapshot.exit_code == 0, from_snapshot.stderr
    assert from_snapshot.stdout.splitlines()[0] == "Gespeichert"
    assert from_snapshot.stdout.splitlines()[1:] == raw.splitlines()[1:]


def test_show_legacy_snapshot_marks_missing_times(env, tmp_path):
    path = snapshot_file(env)
    header, *rows = [
        json.loads(line) for line in path.read_text().splitlines()
    ]
    legacy = (
        tmp_path
        / "codex"
        / SID
        / f"{header['source_digest']}-{header['parser_version']}.jsonl"
    )
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        "".join(
            json.dumps({k: v for k, v in r.items() if k != "type"})
            + "\n"
            for r in rows
        )
    )
    result = runner.invoke(
        app, ["session", "show", "--snapshot", str(legacy)]
    )
    assert result.exit_code == 0, result.stderr
    assert "Beginn — · zuletzt —" in result.stdout


@pytest.fixture
def pager_calls(monkeypatch):
    import pydoc

    calls = []

    def fake_pager(text):
        calls.append((text, os.environ.get("LESS")))

    monkeypatch.setattr(pydoc, "pager", fake_pager)
    monkeypatch.delenv("PAGER", raising=False)
    monkeypatch.delenv("MANPAGER", raising=False)
    monkeypatch.delenv("LESS", raising=False)
    return calls


def test_pager_is_skipped_when_output_is_redirected(env, pager_calls):
    codex_session(env)
    result = runner.invoke(app, [*SHOW, "--pager"])
    assert result.exit_code == 0
    assert pager_calls == []
    assert "1 Mensch" in result.stdout
    assert "\x1b[" not in result.stdout


def test_pager_at_terminal_gets_colors_and_less_r(
    env, pager_calls, monkeypatch
):
    monkeypatch.setenv("TTY_COMPATIBLE", "1")
    # Farben hängen sonst vom Terminal des Testlaufs ab.
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.delenv("NO_COLOR", raising=False)
    codex_session(env)
    result = runner.invoke(app, [*SHOW, "--pager"])
    assert result.exit_code == 0, result.stderr
    [(text, less)] = pager_calls
    assert "Mensch" in text and "\x1b[" in text
    assert less == "-R"
    assert "LESS" not in os.environ


@pytest.mark.parametrize(
    "env_vars, expected",
    [
        ({"LESS": "-FRX"}, "-FRX"),
        ({"LESS": "-F"}, "-F -R"),
        ({"PAGER": "more"}, None),
        ({"PAGER": "/usr/bin/less -S"}, "-R"),
    ],
)
def test_less_options_are_only_extended_for_less(
    env, pager_calls, monkeypatch, env_vars, expected
):
    monkeypatch.setenv("TTY_COMPATIBLE", "1")
    for key, value in env_vars.items():
        monkeypatch.setenv(key, value)
    codex_session(env)
    assert runner.invoke(app, [*SHOW, "--pager"]).exit_code == 0
    assert pager_calls[0][1] == expected
    assert os.environ.get("LESS") == env_vars.get("LESS")


def test_early_pager_close_is_an_expected_end(env, monkeypatch):
    import pydoc

    from ki_dev import session_output

    def closed(_text):
        raise BrokenPipeError

    silenced = []
    monkeypatch.setattr(pydoc, "pager", closed)
    monkeypatch.setattr(
        session_output, "silence_stdout", lambda: silenced.append(1)
    )
    monkeypatch.setenv("TTY_COMPATIBLE", "1")
    codex_session(env)
    result = runner.invoke(app, [*SHOW, "--pager"])
    assert result.exit_code == 0
    assert silenced == [1]
    assert "Traceback" not in result.stdout + result.stderr


def test_export_markdown_and_jsonl_carry_the_same_content(env):
    codex_session(env, [user(1, "t0", "# Kopf\n\n- a"), *dialog(1)[1:]])
    markdown = runner.invoke(app, [*EXPORT, "--format", "markdown"])
    jsonl_out = runner.invoke(
        app, [*EXPORT, "--format", "jsonl", "--title", "Export"]
    )
    assert markdown.exit_code == jsonl_out.exit_code == 0
    assert markdown.stderr == jsonl_out.stderr == ""
    header, *rows = [
        json.loads(line) for line in jsonl_out.stdout.splitlines()
    ]
    assert header["type"] == "transcript_meta"
    assert header["title"] == "Export"
    positions = [markdown.stdout.index(row["text"]) for row in rows]
    assert positions == sorted(positions)
    assert markdown.stdout.startswith(f"# codex-Sitzung {SID}\n")
    assert all_files(env) == []


def test_export_jsonl_matches_the_stored_snapshot(env):
    path = snapshot_file(env)
    result = runner.invoke(
        app,
        [
            "session",
            "export",
            "--snapshot",
            str(path),
            "--format",
            "jsonl",
        ],
    )
    assert result.exit_code == 0, result.stderr
    assert result.stdout_bytes == path.read_bytes()


def test_export_jsonl_without_title_preserves_missing_title(env):
    codex_session(env)
    result = runner.invoke(app, [*EXPORT, "--format", "jsonl"])
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[0])["title"] is None


def test_export_output_creates_a_new_file_only(env):
    codex_session(env)
    target = env.work / "out.md"
    args = [*EXPORT, "--format", "markdown", "--output", str(target)]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.stderr
    assert first.stdout == ""
    content = target.read_text()
    assert "1 Mensch" in content
    target.write_text("vorher")
    again = runner.invoke(app, args)
    assert again.exit_code == 1
    assert "existiert bereits" in again.stderr
    assert target.read_text() == "vorher"


@pytest.mark.parametrize(
    "args",
    [
        ["session", "show"],
        ["session", "show", SID],
        ["session", "show", "--agent", "codex"],
        ["session", "show", SID, "--agent", "codex", "--snapshot", "x"],
        ["session", "show", "--agent", "codex", "--snapshot", "x"],
        ["session", "export", SID, "--agent", "codex"],
        [*EXPORT, "--format", "pdf"],
        [*EXPORT, "--format", "markdown", "--title", "!!!"],
        ["session", "show", "../x", "--agent", "codex"],
    ],
)
def test_bad_selection_exits_2_without_output(env, args):
    codex_session(env)
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert result.stdout == ""


def test_unknown_snapshot_format_is_a_clean_error(env):
    path = env.work / "alt.jsonl"
    path.write_text(
        json.dumps({"role": "benutzer", "text": SECRET}) + "\n"
    )
    result = runner.invoke(
        app, ["session", "show", "--snapshot", str(path)]
    )
    assert result.exit_code == 1
    assert "unbekanntes Snapshot-Format" in result.stderr
    assert SECRET not in result.stdout + result.stderr
