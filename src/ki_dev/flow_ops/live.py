"""Live-Ansicht eines Agenten-Turns: neue Beiträge der Sitzung als
Rich-Markdown und eine Statuszeile mit laufendem Token-Zähler.

:class:`LiveExecutor` umhüllt einen Executor (claude, codex). Während
``send_turn`` liest ein Hintergrund-Thread die Sitzung über denselben
Vertrag wie ``ki-dev session show`` (:func:`read_session_transcript`)
und den Kontextmesswert des Executors. Die Ansicht schreibt nur nach
stderr; Ergebnis und Ablauf des Turns bleiben unberührt.

Eine laufende Sitzungsdatei kann mitten in einer Zeile stehen; dann
ist das Transkript für diesen Takt nicht lesbar. Die Statuszeile nennt
das sichtbar, der nächste Takt liest erneut (benannter Anlass, kein
stiller Ersatz).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from rich.console import Console
from rich.live import Live
from rich.text import Text

from ki_dev.adapter.executors import Executor
from ki_dev.adapter.executors.contract import (
    ContextStatus,
    TurnRequest,
    TurnResult,
)
from ki_dev.adapter.executors.session_transcript import TranscriptError
from ki_dev.adapter.executors.transcript import read_session_transcript
from ki_dev.session_view import message_renderable

INTERVAL_S = 1.0


class LiveExecutor:
    """Executor mit Live-Ansicht; alles außer ``send_turn`` geht
    unverändert an den umhüllten Executor."""

    def __init__(self, inner: Executor, role: str, console: Console):
        self._inner = inner
        self._role = role
        self._console = console

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)

    def send_turn(self, request: TurnRequest) -> TurnResult:
        watch = _Watch(
            self._inner, request.session_id, self._role, self._console
        )
        watch.start()
        try:
            return self._inner.send_turn(request)
        finally:
            watch.stop()


@dataclass
class _Watch:
    executor: Executor
    session_id: str | None
    role: str
    console: Console
    _stop: threading.Event = field(default_factory=threading.Event)
    _shown: int = 0
    _problem: str = ""
    _started: float = field(default_factory=time.monotonic)

    def start(self) -> None:
        # Vorhandene Beiträge gehören zu früheren Turns.
        self._shown = self._message_count()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        with Live(
            self._status(),
            console=self.console,
            refresh_per_second=4,
            transient=True,
        ) as live:
            while not self._stop.wait(INTERVAL_S):
                self._show_new(live)
                live.update(self._status())
            self._show_new(live)

    def _show_new(self, live: Live) -> None:
        try:
            messages = self._read().messages
        except TranscriptError as exc:
            self._problem = (exc.problems or (str(exc),))[0]
            return
        self._problem = ""
        for message in messages[self._shown :]:
            live.console.print(message_renderable(message))
        self._shown = max(self._shown, len(messages))

    def _status(self) -> Text:
        elapsed = int(time.monotonic() - self._started)
        line = Text(
            f"{self.role} · {self._agent()} · "
            f"{elapsed // 60:02d}:{elapsed % 60:02d} · "
            f"{_tokens(self.executor, self.session_id)}",
            style="bold",
        )
        if self._problem:
            line.append(f" · Transkript: {self._problem}", style="dim")
        return line

    def _message_count(self) -> int:
        try:
            return len(self._read().messages)
        except TranscriptError:
            # Noch nicht lesbar (z. B. neue Sitzung ohne Datei): alles
            # Folgende ist neu; den Grund zeigt die Statuszeile.
            return 0

    def _read(self):
        if self.session_id is None:
            # Die ID einer neuen Sitzung vergibt erst der Adapter.
            raise TranscriptError(("neue Sitzung ohne bekannte ID",))
        return read_session_transcript(self._agent(), self.session_id)

    def _agent(self) -> str:
        # Adapter heißen "claude-cli", ihre Transkripte "claude".
        return self.executor.name.removesuffix("-cli")


def _tokens(executor: Executor, session_id: str | None) -> str:
    if session_id is None:
        return f"Kontext {ContextStatus.UNAVAILABLE.value}"
    measurement = executor.measure_context(session_id)
    if measurement.status is ContextStatus.MEASURED:
        return f"Kontext {measurement.tokens / 1000:.1f}k Tokens"
    return f"Kontext {measurement.status.value}"
