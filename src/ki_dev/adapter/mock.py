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
    BuildReport,
    BuildRequest,
    ReviewRequest,
)

NAME = "mock"


@dataclass
class MockBuilder:
    path: str = "MOCK.md"
    calls: int = 0

    def build(self, request: BuildRequest) -> BuildReport:
        self.calls += 1
        target = Path(request.task.workdir) / self.path
        with target.open("a", encoding="utf-8") as handle:
            handle.write(f"Runde {request.round_id}\n")
        return BuildReport(f"mock: {self.path} um Runde ergänzt")


@dataclass
class MockReviewer:
    """Spielt Urteile ``PASS``, ``CHANGES``, ``NEEDS_DECISION`` ab."""

    actions: list[str] = field(default_factory=lambda: ["PASS"])
    calls: int = 0

    def review(self, request: ReviewRequest) -> str:
        if self.calls >= len(self.actions):
            raise RuntimeError("mock: keine Antwort mehr vorgegeben")
        action = self.actions[self.calls]
        self.calls += 1
        refs = request.task.acceptance_criterion_refs()
        return json.dumps(
            {
                "run_id": request.task.run_id,
                "round_id": request.round_id,
                "action": action,
                "detail": "" if action == "PASS" else f"mock {action}",
                "requirement_ref": (
                    refs[0] if action == "CHANGES" else None
                ),
            }
        )
