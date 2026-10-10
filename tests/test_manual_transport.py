"""Transport des Boten (ki-dev-ablauf-qu7.4, Entscheidung A): ``run``
und ``step`` übergeben über dieselbe Adapterfunktion; nur die
Transportart unterscheidet sich."""

from __future__ import annotations

import io
import json

import pytest
from typer.testing import CliRunner

from ki_dev.adapter import manual
from ki_dev.adapter.contract import RunTask, WorkRequest
from ki_dev.adapter.manual import (
    Console,
    Inbox,
    ManualInputPending,
    ManualRelay,
    TransportReadError,
)
from ki_dev.cli import app
from ki_dev.step import cli as step_cli
from tests.fake_bd_command import BdScript
from tests.guideline_fixtures import write_guidelines
from tests.test_step_cli import FULL

runner = CliRunner()


def test_step_binds_the_very_same_send_function():
    assert step_cli.send is manual.send


def test_run_and_step_hand_over_through_the_same_function(
    monkeypatch, tmp_path, tmp_path_factory
):
    calls = []
    original = manual.send

    def spy(transport, key, prompt):
        calls.append((type(transport).__name__, key, prompt))
        original(transport, key, prompt)

    monkeypatch.setattr(manual, "send", spy)
    monkeypatch.setattr(step_cli, "send", spy)

    task = RunTask(
        "run-1", "Auftrag", (), tmp_path, "write",
        acceptance_criteria=("K",),
    )
    relay = ManualRelay(Inbox(tmp_path / "inbox"), "worker")
    with pytest.raises(ManualInputPending):
        relay.work(WorkRequest(task, 1, "Bauauftrag", "a-1"))

    BdScript(
        tmp_path_factory.mktemp("bd"), stdout=json.dumps([FULL])
    ).install(monkeypatch)
    write_guidelines(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["step", "x-1", "--step", "implement"])
    assert result.exit_code == 0, result.stderr

    assert [name for name, _, _ in calls] == ["Inbox", "Console"]
    assert calls[0][2] == "Bauauftrag"
    assert calls[1][2] == result.stdout
    assert calls[1][1] == "x-1:1"


def test_console_writes_and_reads_bounded(tmp_path):
    written = []
    console = Console(written.append, lambda: io.BytesIO(b"abcdef"))
    manual.send(console, "k", "Eingabe")
    assert written == ["Eingabe"]
    assert console.receive("-", 3, "Antwort") == "abcd"
    path = tmp_path / "a.txt"
    path.write_text("äö", encoding="utf-8")
    assert console.receive(str(path), 10, "Antwort") == "äö"


def test_console_read_errors_name_the_input_not_its_text(tmp_path):
    console = Console(print, lambda: io.BytesIO(b"\xff"))
    with pytest.raises(TransportReadError, match="Antwort ist kein"):
        console.receive("-", 10, "Antwort")
    with pytest.raises(TransportReadError, match="nicht lesbar"):
        console.receive(str(tmp_path / "fehlt"), 10, "Antwort")


def _request(tmp_path):
    task = RunTask(
        "run-1", "Auftrag", (), tmp_path, "write",
        acceptance_criteria=("K",),
    )
    return WorkRequest(task, 1, "Bauauftrag", "a-1")


def test_console_relay_writes_prompt_and_reads_stdin(tmp_path):
    """Adapter manual mit Konsole: Eingabe auf stdout, Rahmen für den
    Menschen getrennt (stderr), Antwort von stdin."""
    written, notes = [], []
    console = Console(
        written.append, lambda: io.BytesIO(b"Gebaut."), notes.append
    )
    report = ManualRelay(console, "worker").work(_request(tmp_path))
    assert report.summary == "Gebaut."
    assert written == ["Bauauftrag"]
    assert "Strg-D" in notes[-1]


def test_console_relay_halts_on_empty_answer(tmp_path):
    console = Console(print, lambda: io.BytesIO(b"  \n"))
    with pytest.raises(ManualInputPending, match="resume"):
        ManualRelay(console, "worker").work(_request(tmp_path))


def test_console_relay_rejects_overlong_answer(monkeypatch, tmp_path):
    monkeypatch.setattr(manual, "ANSWER_MAX_CHARS", 3)
    console = Console(print, lambda: io.BytesIO(b"abcdef"))
    with pytest.raises(TransportReadError, match="länger"):
        ManualRelay(console, "worker").work(_request(tmp_path))


def test_inbox_answer_counts_only_when_not_blank(tmp_path):
    inbox = Inbox(tmp_path)
    assert inbox.receive("k") is None
    inbox.answer("k").write_text("  \n", encoding="utf-8")
    assert inbox.receive("k") is None
    inbox.answer("k").write_text("Antwort", encoding="utf-8")
    assert inbox.receive("k") == "Antwort"
