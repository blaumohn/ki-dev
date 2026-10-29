"""CLI-Nachweise für Zeitraum, Quellenkonfiguration und Teilfehler."""

import json
import os

import pytest
from typer.testing import CliRunner

from ki_dev import session_archive, session_list
from ki_dev.adapter.executors import (
    codex_transcript,
    session_config,
)
from ki_dev.cli import app
from tests import claude_session_fixtures as claude
from tests.codex_session_fixtures import (
    dialog,
    session_meta,
    write_session,
)

runner = CliRunner()
SID = "0199aaaa-bbbb-cccc-dddd-eeeeffff0001"
OTHER = "0199bbbb-bbbb-cccc-dddd-eeeeffff0002"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    codex = tmp_path / "codex"
    projects = tmp_path / "claude"
    codex.mkdir()
    projects.mkdir()
    monkeypatch.setenv("KI_DEV_CODEX_SESSIONS_DIR", str(codex))
    monkeypatch.setenv("KI_DEV_CLAUDE_SESSIONS_DIR", str(projects))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return tmp_path, codex, projects


def add_codex(root, sid=SID, last="2026-10-28T15:00:00Z", cwd=None):
    meta = session_meta(sid, "2026-09-17T09:00:00Z")
    if cwd is not None:
        meta["payload"]["cwd"] = cwd
    rows = dialog(1)
    rows[-1]["timestamp"] = last
    return write_session(root, sid, [meta, *rows])


def snapshots(work):
    return sorted((work / ".local/var/transcripts").glob("*.jsonl"))


def archive(*args):
    return runner.invoke(app, ["session", "transcript", *args])


def test_since_uses_activity_not_start_or_file_mtime_and_reuses(env):
    work, codex, projects = env
    path = add_codex(codex)
    os.utime(path, (0, 0))
    add_codex(codex, OTHER, "2026-10-27T23:59:59Z")
    claude.write_session(
        projects, claude.SESSION, claude.chain(claude.dialog(1))
    )
    args = ["--since", "2026-10-28", "--until", "2026-10-28"]
    first = archive(*args)
    assert first.exit_code == 0, first.stderr
    [saved] = snapshots(work)
    assert saved.name == "260917T09_codex_0199aaaa.jsonl"
    assert "1 archiviert" in first.stderr
    assert "2 außerhalb" in first.stderr
    before = saved.stat().st_mtime_ns
    again = archive(*args)
    assert again.exit_code == 0, again.stderr
    assert again.stdout == first.stdout
    assert saved.stat().st_mtime_ns == before
    path.write_text(path.read_text() + "\n")
    assert archive(*args).exit_code == 0
    assert len(snapshots(work)) == 2


@pytest.mark.parametrize(
    ("timestamp", "selected"),
    [
        ("2026-10-28T00:00:00Z", True),
        ("2026-10-28T23:59:59.999Z", True),
        ("2026-10-29T00:00:00Z", False),
        ("2026-10-27T23:59:59Z", False),
        ("2026-10-29T01:00:00+02:00", True),
    ],
)
def test_date_bounds_are_utc_and_until_includes_day(
    env, timestamp, selected
):
    work, codex, _ = env
    add_codex(codex, last=timestamp)
    result = archive("--since", "2026-10-28", "--until", "2026-10-28")
    assert result.exit_code == 0, result.stderr
    assert bool(snapshots(work)) is selected


def test_timestamp_upper_bound_is_exclusive(env):
    work, codex, _ = env
    add_codex(codex)
    result = archive(
        "--since",
        "2026-10-28T17:00:00+02:00",
        "--until",
        "2026-10-28T15:00:01Z",
    )
    assert result.exit_code == 0, result.stderr
    assert len(snapshots(work)) == 1
    result = archive(
        "--until", "2026-10-28T15:00:00Z", "--dir", "empty"
    )
    assert result.exit_code == 0, result.stderr
    assert not (work / "empty").exists()


@pytest.mark.parametrize(
    "args",
    [
        ["--since", "gestern"],
        ["--since", "2026-02-30"],
        ["--since", "2026-10-28T15:00:00"],
        ["--since", "2026-10-29", "--until", "2026-10-28"],
        [SID, "--agent", "codex", "--since", "2026-10-28"],
        [SID, "--agent", "codex", "--all"],
        ["--all", "--agent", "other"],
    ],
)
def test_invalid_batch_calls_write_nothing(env, args):
    work, codex, _ = env
    add_codex(codex)
    result = archive(*args)
    assert result.exit_code == 2, result.stderr
    assert snapshots(work) == []


def test_unusable_session_does_not_abort_batch_but_sets_exit_1(env):
    work, codex, _ = env
    add_codex(codex)
    write_session(codex, OTHER, [{"secret": "DO-NOT-PRINT"}])
    result = archive("--since", "2026-10-28")
    assert result.exit_code == 1
    assert len(snapshots(work)) == 1
    assert OTHER in result.stderr
    assert "1 Fehler" in result.stderr
    assert "DO-NOT-PRINT" not in result.stdout + result.stderr


def test_project_sources_work_for_batch_list_and_explicit_id(
    env, monkeypatch
):
    work, codex, projects = env
    monkeypatch.delenv("KI_DEV_CODEX_SESSIONS_DIR")
    monkeypatch.delenv("KI_DEV_CLAUDE_SESSIONS_DIR")
    (work / "pyproject.toml").write_text(
        '[tool.ki-dev.session]\ncodex_sessions_dir = "codex"\n'
        'claude_sessions_dir = "claude"\n'
    )
    add_codex(codex)
    claude.write_session(
        projects, claude.SESSION, claude.chain(claude.dialog(1))
    )
    listed = runner.invoke(app, ["session", "list"])
    assert listed.exit_code == 0, listed.stderr
    assert SID in listed.stdout and claude.SESSION in listed.stdout
    single = archive(SID, "--agent", "codex")
    assert single.exit_code == 0, single.stderr
    batch = archive("--all")
    assert batch.exit_code == 0, batch.stderr
    assert len(snapshots(work)) == 2


def test_configured_cwd_filter_is_shared_and_overridable(env):
    work, codex, _ = env
    (work / "pyproject.toml").write_text(
        '[tool.ki-dev.session]\nexclude_cwd = ["/specific/tests/*"]\n'
    )
    add_codex(codex, cwd="/specific/tests/run-1")
    add_codex(codex, OTHER, cwd="/tmp/real-project")
    listed = runner.invoke(app, ["session", "list"])
    assert SID not in listed.stdout and OTHER in listed.stdout
    result = archive("--all")
    assert result.exit_code == 0, result.stderr
    assert len(snapshots(work)) == 1
    result = archive("--all", "--include-tests")
    assert result.exit_code == 0, result.stderr
    assert len(snapshots(work)) == 2


@pytest.mark.parametrize("value", ['""', "7", '["x"]'])
def test_invalid_source_configuration_is_not_a_default(env, value):
    work, _, _ = env
    (work / "pyproject.toml").write_text(
        f"[tool.ki-dev.session]\ncodex_sessions_dir = {value}\n"
    )
    result = archive("--all")
    assert result.exit_code == 1
    assert "codex_sessions_dir" in result.stderr
    assert snapshots(work) == []


@pytest.mark.parametrize(
    "document",
    [
        "tool = 7",
        '[tool]\nki-dev = "invalid"',
        "[tool.ki-dev]\nsession = false",
        "[tool.ki-dev.session]\nexclude_cwd = [7]",
        '[tool.ki-dev.session]\nunknown = "secret"',
        "[tool.ki-dev.session",
    ],
)
def test_damaged_configuration_is_reported_without_traceback(
    env, document
):
    work, _, _ = env
    (work / "pyproject.toml").write_text(document)
    result = archive("--all")
    assert result.exit_code == 1
    assert "Traceback" not in result.stderr
    assert "secret" not in result.stderr
    assert snapshots(work) == []


def test_explicit_environment_source_takes_precedence(env):
    work, codex, _ = env
    (work / "pyproject.toml").write_text(
        '[tool.ki-dev.session]\ncodex_sessions_dir = "unused"\n'
    )
    add_codex(codex)
    result = archive("--all", "--agent", "codex")
    assert result.exit_code == 0, result.stderr
    assert len(snapshots(work)) == 1


def test_unknown_activity_is_reported_but_other_sessions_are_saved(env):
    work, codex, _ = env
    add_codex(codex)
    write_session(codex, OTHER, dialog(1))
    result = archive("--since", "2026-10-28")
    assert result.exit_code == 1
    assert "last_activity_at" in result.stderr
    assert len(snapshots(work)) == 1


@pytest.mark.parametrize("agent", ["codex", "claude"])
@pytest.mark.parametrize(
    ("option", "stamp"),
    [
        ("--since", "2025-01-01T10:00:00Z"),
        ("--until", "2027-01-01T10:00:00Z"),
    ],
)
def test_old_unusable_session_is_outside_before_dialog_validation(
    env, agent, option, stamp, monkeypatch
):
    work, codex, projects = env
    add_codex(codex)
    if agent == "codex":
        write_session(codex, OTHER, [session_meta(OTHER, stamp)])
    else:
        rows = claude.chain(
            [claude.human("Alte Eingabe", origin={"kind": "sdk"})]
        )
        rows[0]["timestamp"] = stamp
        claude.write_session(projects, claude.SESSION, rows)
    actual_parse = session_archive.parse_session_source

    def selected_only(ref, data):
        assert ref.session_id not in (OTHER, claude.SESSION)
        return actual_parse(ref, data)

    monkeypatch.setattr(
        session_archive, "parse_session_source", selected_only
    )
    result = archive(option, "2026-10-28")
    assert result.exit_code == 0, result.stderr
    assert len(snapshots(work)) == 1
    assert "1 außerhalb des Zeitraums; 0 Fehler" in result.stderr


@pytest.mark.parametrize(
    "args",
    [
        ["--since", "2026-10-28"],
        ["--all"],
    ],
)
def test_selected_empty_session_remains_an_error(env, args):
    work, codex, _ = env
    add_codex(codex)
    write_session(
        codex, OTHER, [session_meta(OTHER, "2026-10-28T12:00:00Z")]
    )
    result = archive(*args)
    assert result.exit_code == 1
    assert "keine Dialognachrichten" in result.stderr
    assert len(snapshots(work)) == 1


def test_damaged_raw_time_cannot_prove_an_old_session_is_outside(env):
    work, codex, _ = env
    add_codex(codex)
    path = write_session(
        codex, OTHER, [session_meta(OTHER, "2025-01-01T10:00:00Z")]
    )
    with path.open("a") as handle:
        handle.write('{"timestamp": "2026-10-28T12:00:00Z"\n')
    result = archive("--since", "2026-10-28")
    assert result.exit_code == 1
    assert OTHER in result.stderr
    assert "1 Fehler" in result.stderr
    assert len(snapshots(work)) == 1


@pytest.mark.parametrize(
    "timestamp",
    [
        "2025-01-01T10:00:00Z",
        "2027-01-01T10:00:00Z",
    ],
)
def test_last_raw_line_does_not_replace_dialog_activity(env, timestamp):
    work, codex, _ = env
    path = add_codex(codex)
    with path.open("a") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "event_msg",
                    "timestamp": timestamp,
                    "payload": {"type": "token_count"},
                }
            )
            + "\n"
        )
    result = archive("--since", "2026-10-28", "--until", "2026-10-28")
    assert result.exit_code == 0, result.stderr
    assert len(snapshots(work)) == 1


def test_batch_reads_configuration_once_and_uses_catalog_paths(
    env, monkeypatch
):
    work, codex, _ = env
    add_codex(codex)
    add_codex(codex, OTHER)
    actual_config = session_config.read_session_config
    reads = []

    def config_once():
        reads.append(1)
        return actual_config()

    def no_lookup(*_args):
        pytest.fail(
            "Batch darf Sitzungs-IDs nicht erneut per Glob suchen"
        )

    monkeypatch.setattr(
        session_list, "read_session_config", config_once
    )
    monkeypatch.setattr(
        session_config, "read_session_config", config_once
    )
    monkeypatch.setattr(
        codex_transcript, "find_session_rollouts", no_lookup
    )
    result = archive("--all")
    assert result.exit_code == 0, result.stderr
    assert len(reads) == 1
    assert len(snapshots(work)) == 2


def test_direct_catalog_paths_do_not_hide_ambiguous_session_ids(env):
    work, codex, _ = env
    path = add_codex(codex)
    write_session(
        codex,
        SID,
        [session_meta(SID), *dialog(1)],
        day="2026/09/18",
    )
    assert path.exists()
    result = archive("--all")
    assert result.exit_code == 1
    assert "mehrdeutig" in result.stderr
    assert snapshots(work) == []
