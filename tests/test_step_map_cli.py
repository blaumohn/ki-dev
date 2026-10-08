import json

import pytest
from typer.testing import CliRunner

from ki_dev.cli import app
from ki_dev.step import beads_source
from tests import claude_session_fixtures as claude
from tests.codex_session_fixtures import (
    SECRET,
    assistant,
    dialog,
    noise,
    session_meta,
    user,
)
from tests.codex_session_fixtures import (
    write_session as write_raw_session,
)
from tests.fake_bd import FakeBd
from tests.guideline_fixtures import write_guidelines

runner = CliRunner()
SID = "0199aaaa-bbbb-cccc-dddd-eeeeffff0001"
TITLE = ["--title", "Test-Import"]
MAP = ["step", "map", "--agent", "codex", "--session", SID, *TITLE]


def write_session(root, session_id, rows, day="2026/09/17"):
    """Codex-Sitzung mit belegtem Beginn (Snapshot-Name braucht ihn)."""
    rows = [session_meta(session_id), *rows]
    return write_raw_session(root, session_id, rows, day=day)


@pytest.fixture
def env(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    write_guidelines(work)
    bd = FakeBd(tmp_path, SECRET)
    bd.install(monkeypatch)
    monkeypatch.setenv("KI_DEV_CODEX_SESSIONS_DIR", str(sessions))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.chdir(work)
    env.sessions, env.work, env.bd = sessions, work, bd
    return env


def artifacts(work):
    return sorted((work / ".local").rglob("*.jsonl"))


def messages(artifact):
    """Nachrichtenzeilen eines Snapshots (ohne Kopfzeile)."""
    lines = artifact.read_text().splitlines()
    assert json.loads(lines[0])["type"] == "transcript_meta"
    return [json.loads(line) for line in lines[1:]]


def leaked(result) -> bool:
    return SECRET in result.stdout + result.stderr


def test_map_call_writes_source_bead_and_prints_short_task(env):
    write_session(env.sessions, SID, dialog(2))
    result = runner.invoke(app, MAP)
    assert result.exit_code == 0, result.stderr
    [artifact] = artifacts(env.work)
    assert artifact.name == "260917T09_test-import_0199aaaa.jsonl"
    assert len(messages(artifact)) == 4
    [bead] = env.bd.rows
    rel = artifact.relative_to(env.work).as_posix()
    assert bead["metadata"]["handoff"]["source_refs"] == [rel]
    assert "Schritt: map" in result.stdout
    assert f"Bead: {bead['id']}" in result.stdout
    assert rel in result.stdout
    assert "abschnittsweise" in result.stdout
    assert "Frage 0" not in result.stdout


def test_no_transcript_text_on_stdout_or_in_beads(env):
    write_session(
        env.sessions,
        SID,
        [user(1, text=SECRET), assistant(2, text=SECRET)],
    )
    result = runner.invoke(app, MAP)
    assert result.exit_code == 0
    assert not leaked(result)
    assert SECRET not in json.dumps(env.bd.rows)
    assert SECRET in artifacts(env.work)[0].read_text()


def test_repeat_gives_same_bead_and_artifact(env):
    write_session(env.sessions, SID, dialog(1))
    first = runner.invoke(app, MAP)
    files = artifacts(env.work)
    content = files[0].read_bytes()
    second = runner.invoke(app, MAP)
    assert first.stdout == second.stdout
    assert artifacts(env.work) == files
    assert files[0].read_bytes() == content
    assert len(env.bd.rows) == 1
    assert env.bd.commands().count("create") == 1


def test_changed_session_makes_a_new_source_and_keeps_the_old(env):
    path = write_session(env.sessions, SID, dialog(1))
    runner.invoke(app, MAP)
    old = artifacts(env.work)[0]
    old_bytes = old.read_bytes()
    path.write_text(path.read_text() + "\n")
    result = runner.invoke(app, MAP)
    assert result.exit_code == 0
    assert len(artifacts(env.work)) == 2
    assert old.read_bytes() == old_bytes
    assert len(env.bd.rows) == 2


def test_bd_failure_keeps_the_valid_artifact_and_retry_reuses_it(env):
    write_session(env.sessions, SID, dialog(1))
    env.bd.set(fail_on="create")
    failed = runner.invoke(app, MAP)
    assert failed.exit_code == 1
    assert "Exit-Code 3" in failed.stderr
    assert not leaked(failed)
    assert "Schritt: map" not in failed.stdout
    [artifact] = artifacts(env.work)
    before = artifact.stat().st_mtime_ns
    env.bd.set(fail_on=None)
    retry = runner.invoke(app, MAP)
    assert retry.exit_code == 0
    assert artifact.stat().st_mtime_ns == before
    assert len(env.bd.rows) == 1


def test_ambiguous_source_beads_abort(env):
    write_session(env.sessions, SID, dialog(1))
    runner.invoke(app, MAP)
    env.bd.set(rows=env.bd.rows * 2)
    result = runner.invoke(app, MAP)
    assert result.exit_code == 1
    assert "2 Quellen-Beads" in result.stderr
    assert "Schritt: map" not in result.stdout


def test_bd_timeout_exits_1(env, monkeypatch):
    write_session(env.sessions, SID, dialog(1))
    monkeypatch.setattr(beads_source, "BD_TIMEOUT_S", 0.5)
    env.bd.set(hang="list")
    result = runner.invoke(app, MAP)
    assert result.exit_code == 1
    assert "nicht innerhalb" in result.stderr


def test_reused_bead_without_matching_reference_is_rejected(env):
    write_session(env.sessions, SID, dialog(1))
    runner.invoke(app, MAP)
    rows = env.bd.rows
    rows[0]["metadata"]["handoff"]["source_refs"] = ["anderswo.jsonl"]
    env.bd.set(rows=rows)
    result = runner.invoke(app, MAP)
    assert result.exit_code == 1
    assert "verweist nicht" in result.stderr


@pytest.mark.parametrize(
    "rows, code",
    [
        ([user(1, text=SECRET), assistant(1, text=SECRET)], "T3"),
        (noise(), "T0"),
        ([user(1), assistant(2, phase=SECRET)], "T5"),
    ],
)
def test_invalid_dialog_fails_without_bead_artifact_or_content(
    env, rows, code
):
    write_session(env.sessions, SID, rows)
    result = runner.invoke(app, MAP)
    assert result.exit_code == 1
    assert code in result.stderr
    assert "kein bewiesener CLI-Versionswechsel" in result.stderr
    assert not leaked(result)
    assert result.stdout == ""
    assert artifacts(env.work) == []
    assert env.bd.rows == []
    assert env.bd.get()["calls"] == []


@pytest.mark.parametrize(
    "rows, counter",
    [
        (
            [user(1, text=SECRET), user(2), assistant(3)],
            "T4_role_breaks",
        ),
        (
            [user(1), assistant(2), user(3, text=SECRET)],
            "T2_count_mismatch",
        ),
        ([user(1, text=SECRET)], "T1_single_role"),
    ],
)
def test_advisory_dialog_variants_pass_completely(env, rows, counter):
    write_session(env.sessions, SID, rows)
    result = runner.invoke(app, MAP)
    assert result.exit_code == 0, result.stderr
    assert not leaked(result)
    [artifact] = artifacts(env.work)
    stored = messages(artifact)
    assert [row["ordinal"] for row in stored] == [
        r["ordinal"] for r in rows
    ]
    assert [row["position"] for row in stored] == list(
        range(1, len(rows) + 1)
    )


def test_claude_session_is_mapped_through_the_same_path(
    env, monkeypatch
):
    claude_root = env.sessions.parent / "claude-projects"
    monkeypatch.setenv("KI_DEV_CLAUDE_SESSIONS_DIR", str(claude_root))
    rows = claude.chain(
        [claude.human(SECRET), claude.human("Nachtrag"), claude.reply()]
    )
    claude.write_session(claude_root, claude.SESSION, rows)
    args = ["step", "map", "--agent", "claude", "--session"]
    result = runner.invoke(app, [*args, claude.SESSION, *TITLE])
    assert result.exit_code == 0, result.stderr
    assert not leaked(result)
    assert SECRET not in json.dumps(env.bd.rows)
    [artifact] = artifacts(env.work)
    assert artifact.name.endswith(f"_{claude.SESSION[:8]}.jsonl")
    header = json.loads(artifact.read_text().splitlines()[0])
    assert header["agent"] == "claude"
    stored = messages(artifact)
    assert [row["ordinal"] for row in stored] == [None, None, None]
    assert [row["role"] for row in stored] == [
        "user",
        "user",
        "assistant",
    ]


def test_claude_empty_sessions_dir_variable_is_a_clean_error(
    env, monkeypatch
):
    monkeypatch.setenv("KI_DEV_CLAUDE_SESSIONS_DIR", "")
    args = ["step", "map", "--agent", "claude", "--session"]
    result = runner.invoke(app, [*args, claude.SESSION, *TITLE])
    _assert_clean_failure(
        result, env, "KI_DEV_CLAUDE_SESSIONS_DIR ist gesetzt, aber leer"
    )


def test_truncated_json_fails_visibly(env):
    path = write_session(env.sessions, SID, dialog(1))
    path.write_text(path.read_text() + '{"type": "event_')
    result = runner.invoke(app, MAP)
    assert result.exit_code == 1
    assert "J1" in result.stderr
    assert artifacts(env.work) == []


@pytest.mark.parametrize(
    "args",
    [
        *(
            [*args, *TITLE]
            for args in (
                ["step", "map", "--agent", "codex"],
                ["step", "map", "--session", SID],
                ["step", "map", "--agent", "gemini", "--session", SID],
                ["step", "map", "--agent", "", "--session", SID],
                [
                    "step",
                    "map",
                    "--agent",
                    "codex",
                    "--session",
                    "../x",
                ],
                ["step", "map", "--agent", "codex", "--session", "a*"],
                ["step", "map", "--agent", "codex", "--session", ""],
                ["step", "--agent", "codex", "--session", SID],
                ["step", "x-1", "--agent", "codex", "--session", SID],
                [
                    "step",
                    "map",
                    "x-1",
                    "--agent",
                    "codex",
                    "--session",
                    SID,
                ],
                ["step", "--agent", "codex"],
                ["step", "--session", SID],
                [
                    "step",
                    "--step",
                    "map",
                    "--agent",
                    "codex",
                    "--session",
                    SID,
                ],
                [
                    "step",
                    "map",
                    "--step",
                    "map",
                    "--agent",
                    "codex",
                    "--session",
                    SID,
                ],
            )
        ),
        ["step", "map", "--agent", "codex", "--session", SID],
        [*MAP[:-1], ""],
        [*MAP[:-1], " "],
        [*MAP[:-1], "!!!"],
        [*MAP[:-1], "x" * 121],
        ["step", "x-1", "--step", "map", *TITLE],
        ["step", "local", *TITLE],
    ],
)
def test_bad_calls_exit_2_before_any_effect(env, args):
    write_session(env.sessions, SID, dialog(1))
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert result.stdout == ""
    assert artifacts(env.work) == []
    assert env.bd.get()["calls"] == []


def test_exact_contract_call_without_extra_words_works(env):
    write_session(env.sessions, SID, dialog(1))
    result = runner.invoke(
        app,
        ["step", "map", "--agent", "codex", "--session", SID, *TITLE],
    )
    assert result.exit_code == 0, result.stderr


def _assert_clean_failure(result, env, *needles):
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "Traceback" not in result.stdout + result.stderr
    for needle in needles:
        assert needle in result.stderr
    assert env.bd.get()["calls"] == []
    assert artifacts(env.work) == []


def test_empty_sessions_dir_variable_is_a_visible_clean_error(
    env, monkeypatch
):
    write_session(env.sessions, SID, dialog(1))
    monkeypatch.setenv("KI_DEV_CODEX_SESSIONS_DIR", "")
    result = runner.invoke(app, MAP)
    _assert_clean_failure(
        result, env, "KI_DEV_CODEX_SESSIONS_DIR ist gesetzt, aber leer"
    )


def test_missing_sessions_dir_is_a_visible_clean_error(
    env, monkeypatch
):
    monkeypatch.setenv(
        "KI_DEV_CODEX_SESSIONS_DIR", str(env.sessions / "fehlt")
    )
    _assert_clean_failure(
        runner.invoke(app, MAP), env, "existiert nicht"
    )


def test_unreadable_session_file_is_sanitized(env):
    directory = env.sessions / "2026" / "09" / "17"
    directory.mkdir(parents=True)
    (directory / f"rollout-2026-09-17T09-10-35-{SID}.jsonl").mkdir()
    result = runner.invoke(app, MAP)
    _assert_clean_failure(result, env, "nicht lesbar", "IsADirectory")
    assert str(env.sessions) not in result.stderr


@pytest.mark.parametrize("bad", [[], {}, 5, None, True])
def test_odd_phase_types_are_t5_not_a_crash(env, bad):
    rows = [user(1), assistant(2, phase=bad)]
    write_session(env.sessions, SID, rows)
    result = runner.invoke(app, MAP)
    _assert_clean_failure(result, env, "T5", "payload.phase")


def test_huge_ordinal_is_accepted_or_diagnosed_without_crash(env):
    rows = [user(10**400), assistant(10**400 + 1)]
    write_session(env.sessions, SID, rows)
    result = runner.invoke(app, MAP)
    assert isinstance(result.exception, (SystemExit, type(None)))
    assert "Traceback" not in result.stdout + result.stderr


def test_missing_and_ambiguous_session_exit_1(env):
    missing = runner.invoke(app, MAP)
    assert missing.exit_code == 1
    assert "nicht gefunden" in missing.stderr
    write_session(env.sessions, SID, dialog(1), day="2026/09/17")
    write_session(env.sessions, SID, dialog(1), day="2026/09/18")
    ambiguous = runner.invoke(app, MAP)
    assert ambiguous.exit_code == 1
    assert "mehrdeutig" in ambiguous.stderr
    assert env.bd.get()["calls"] == []


def test_existing_bead_form_stays_read_only_and_compatible(env):
    env.bd.set(
        rows=[
            {
                "id": "x-1",
                "title": "T",
                "description": "D",
                "metadata": {"handoff": {"source_refs": ["a.md"]}},
            }
        ]
    )
    result = runner.invoke(app, ["step", "x-1", "--step", "map"])
    assert result.exit_code == 0
    assert env.bd.commands() == ["show"]
    assert artifacts(env.work) == []


def test_bead_form_without_step_still_exits_2(env):
    result = runner.invoke(app, ["step", "x-1"])
    assert result.exit_code == 2
    assert env.bd.get()["calls"] == []


def test_help_documents_both_forms_and_their_effects(env):
    result = runner.invoke(app, ["step", "--help"])
    assert result.exit_code == 0
    for text in (
        "--agent codex --session",
        "--step STEP",
        "Korrekturen können Dateien ändern",
        "Schreibt einen datierten Snapshot",
        ".local/var/transcripts/",
        "--title ist Pflicht",
        "Quellen-Bead",
        "bei gleichem Stand wiederverwendet",
        "Statt einer Beads-ID; nicht mit --step kombinieren",
    ):
        assert text in " ".join(result.stdout.split()), text


def test_map_appends_guidelines_after_reading_hint(env):
    write_session(env.sessions, SID, dialog(2))
    result = runner.invoke(app, MAP)
    assert result.exit_code == 0, result.stderr
    text = result.stdout
    assert text.index("abschnittsweise") < text.index("LEITLINIEN")
    assert "- Q0:map-task" in text
    assert "- Q1:common" in text
    assert "graph-task" not in text


def test_map_guideline_error_precedes_any_write(env):
    write_session(env.sessions, SID, dialog(2))
    (env.work / "docs/policies/programmierleitlinie.de.yaml").unlink()
    result = runner.invoke(app, MAP)
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Leitlinienquelle nicht lesbar" in result.stderr
    assert artifacts(env.work) == []
    assert "create" not in env.bd.commands()


def test_reused_bead_with_legacy_reference_stays_valid(env):
    write_session(env.sessions, SID, dialog(1))
    runner.invoke(app, MAP)
    [artifact] = artifacts(env.work)
    header = json.loads(artifact.read_text().splitlines()[0])
    legacy = (
        f".local/handoff/codex/{SID}/"
        f"{header['source_digest']}-{header['parser_version']}.jsonl"
    )
    rows = env.bd.rows
    rows[0]["metadata"]["handoff"]["source_refs"] = [legacy]
    env.bd.set(rows=rows)
    missing = runner.invoke(app, MAP)
    assert missing.exit_code == 1
    assert "verweist nicht" in missing.stderr
    (env.work / legacy).parent.mkdir(parents=True)
    (env.work / legacy).write_text("{}\n")
    result = runner.invoke(app, MAP)
    assert result.exit_code == 0, result.stderr
    assert legacy in result.stdout
    assert env.bd.commands().count("create") == 1


def test_new_title_reuses_the_existing_snapshot(env):
    write_session(env.sessions, SID, dialog(1))
    first = runner.invoke(app, MAP)
    second = runner.invoke(app, [*MAP[:-1], "Anderer Titel"])
    assert second.exit_code == 0, second.stderr
    assert first.stdout == second.stdout
    [artifact] = artifacts(env.work)
    assert "test-import" in artifact.name


def test_session_without_start_fails_before_any_bead(env):
    write_raw_session(env.sessions, SID, dialog(1))
    result = runner.invoke(app, MAP)
    assert result.exit_code == 1
    assert "started_at fehlt" in result.stderr
    assert artifacts(env.work) == []
    assert env.bd.get()["calls"] == []
