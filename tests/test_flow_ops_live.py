"""Live-Ansicht eines Agenten-Turns (``ki-dev -f implement -v``)."""

from __future__ import annotations

import io
import threading
import time

from rich.console import Console

from ki_dev.adapter.executors.contract import (
    ContextMeasurement,
    ContextStatus,
    TurnStatus,
)
from ki_dev.adapter.executors.session_transcript import (
    SessionTranscript,
    TranscriptError,
    TranscriptMessage,
)
from ki_dev.flow_ops import live


def _transcript(texts: list[str]) -> SessionTranscript:
    return SessionTranscript(
        agent="claude",
        session_id="s-1",
        source_digest="d",
        parser_version="1",
        started_at=None,
        last_activity_at=None,
        messages=tuple(
            TranscriptMessage(i, "assistant", text, i, i)
            for i, text in enumerate(texts, 1)
        ),
        diagnostics={},
    )


class FakeExecutor:
    name = "claude"

    def __init__(self, texts: list[str]) -> None:
        self.texts = texts

    def send_turn(self, _request):
        self.texts.append("**neu im Turn**")
        time.sleep(0.05)
        return TurnStatus.OK

    def measure_context(self, _session_id):
        return ContextMeasurement(ContextStatus.MEASURED, tokens=41_200)

    def measure_quota(self, _session_id):
        return "quota"


class _Request:
    session_id = "s-1"


def _console() -> tuple[Console, io.StringIO]:
    out = io.StringIO()
    return Console(file=out, width=80, force_terminal=False), out


def test_turn_shows_only_new_messages_and_keeps_result(monkeypatch):
    texts = ["alter Beitrag"]
    monkeypatch.setattr(live, "INTERVAL_S", 0.01)
    monkeypatch.setattr(
        live,
        "read_session_transcript",
        lambda _agent, _session_id: _transcript(list(texts)),
    )
    console, out = _console()
    executor = live.LiveExecutor(FakeExecutor(texts), "worker", console)

    assert executor.send_turn(_Request()) is TurnStatus.OK

    shown = out.getvalue()
    assert "neu im Turn" in shown
    assert "alter Beitrag" not in shown


def test_everything_but_the_turn_goes_to_the_inner_executor():
    console, _ = _console()
    executor = live.LiveExecutor(FakeExecutor([]), "review", console)
    assert executor.name == "claude"
    assert executor.measure_quota("s-1") == "quota"
    assert live._tokens(executor, "s-1") == "Kontext 41.2k Tokens"


def test_unreadable_transcript_is_named_in_status(monkeypatch):
    def broken(_agent, _session_id):
        raise TranscriptError(("Zeile 3 unvollständig",))

    monkeypatch.setattr(live, "read_session_transcript", broken)
    console, _ = _console()
    watch = live._Watch(FakeExecutor([]), "s-1", "worker", console)
    watch._show_new(None)
    assert "Zeile 3 unvollständig" in watch._status().plain


class _NewSession:
    session_id = None


def test_new_session_runs_without_id_and_names_the_reason(monkeypatch):
    monkeypatch.setattr(live, "INTERVAL_S", 0.01)
    errors = []
    monkeypatch.setattr(
        threading, "excepthook", lambda args: errors.append(args)
    )
    console, _ = _console()
    executor = live.LiveExecutor(FakeExecutor([]), "worker", console)

    assert executor.send_turn(_NewSession()) is TurnStatus.OK

    assert errors == []
    watch = live._Watch(FakeExecutor([]), None, "worker", console)
    watch._show_new(None)
    status = watch._status().plain
    assert "Kontext unavailable" in status
    assert "neue Sitzung ohne bekannte ID" in status


def test_cli_adapter_name_reads_the_agents_transcript(monkeypatch):
    agents = []

    def read(agent, _session_id):
        agents.append(agent)
        return _transcript([])

    monkeypatch.setattr(live, "read_session_transcript", read)
    inner = FakeExecutor([])
    inner.name = "claude-cli"
    console, _ = _console()
    live._Watch(inner, "s-1", "worker", console)._show_new(None)
    assert agents == ["claude"]
