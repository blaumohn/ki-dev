"""Adapter ``mock``: vorgegebene Antworten statt einer Agentensitzung.

Für Tests und Vorführungen ohne Anbieterzugang. Der Bau schreibt je
Runde eine Zeile in eine Datei des Arbeitsverzeichnisses, damit der
Nachweis eine echte Wirkung sieht; das Review spielt eine Liste von
Urteilen ab und antwortet im selben formalen JSON-Vertrag wie ein
Agent. Eine erschöpfte Liste ist ein sichtbarer Fehler, kein PASS.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ki_dev.adapter.contract import (
    ReviewRequest,
    TurnPrompt,
    WorkReport,
    WorkRequest,
)
from ki_dev.adapter.executors import ExecutorSpec, Measure

NAME = "mock"
CAPABILITIES: frozenset[Measure] = frozenset()


@dataclass
class MockWorker:
    spec: ExecutorSpec
    path: str = "MOCK.md"
    calls: int = 0

    def work(self, request: WorkRequest) -> WorkReport:
        self.calls += 1
        target = Path(request.task.workdir) / self.path
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"Runde {request.round_id}\n")
        return WorkReport(f"mock: {self.path} um Runde ergänzt")


@dataclass
class MockReviewer:
    """Spielt vorgegebene Review-Ereignisse ab (``PASS`` oder eine
    Befundklasse des Ablaufs, z. B. ``fix``)."""

    spec: ExecutorSpec
    events: list[str] = field(default_factory=lambda: ["PASS"])
    calls: int = 0

    def review(self, request: ReviewRequest) -> str:
        if self.calls >= len(self.events):
            raise RuntimeError("mock: keine Antwort mehr vorgegeben")
        event = self.events[self.calls]
        self.calls += 1
        refs = request.task.acceptance_criterion_refs()
        changes = event == request.vocabulary.changes
        return json.dumps(
            {
                "run_id": request.task.run_id,
                "round_id": request.round_id,
                "event": event,
                "detail": "" if event == "PASS" else f"mock {event}",
                "requirement_ref": refs[0] if changes else None,
            }
        )


@dataclass
class MockAnswers:
    """Spielt vorgegebene Antworten auf Übergaben ab; ``{attempt}``
    setzt die Kennung des Versuchs ein. Eine erschöpfte Liste ist ein
    sichtbarer Fehler."""

    spec: ExecutorSpec
    answers: list[str] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)

    def ask(self, request: TurnPrompt) -> str:
        if len(self.prompts) >= len(self.answers):
            raise RuntimeError("mock: keine Antwort mehr vorgegeben")
        answer = self.answers[len(self.prompts)]
        self.prompts.append(request.prompt)
        return answer.replace("{attempt}", request.key)
