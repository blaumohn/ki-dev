"""Belege eines Anforderungstests und frühe Blockade.

Ein Test protokolliert die öffentlichen Befehle, die er ausführt, und
was er beobachtet. Erreicht er das geprüfte Merkmal nicht, weil schon
Laden, Schema oder CLI scheitern, wirft er ``Blocked``: Das Merkmal
gilt dann als nicht geprüft (``not-run``), nicht als inhaltlicher
Fehlschlag; der pytest-Lauf bleibt trotzdem rot.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from tests.spec.schema import BLOCK_STAGES


class Blocked(Exception):
    """Prüfung endet vor dem Merkmal; ``stage`` nennt die Stelle."""

    def __init__(self, stage: str, detail: str):
        if stage not in BLOCK_STAGES:
            raise ValueError(
                f"unbekannte Blockadestelle {stage!r}; "
                f"erlaubt: {', '.join(BLOCK_STAGES)}"
            )
        super().__init__(f"{stage}: {detail}")
        self.stage = stage
        self.detail = detail


@dataclass
class Evidence:
    """Ausgeführte Befehle und Beobachtungen eines Tests."""

    commands: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def command(self, argv) -> None:
        self.commands.append(shlex.join(map(str, argv)))

    def note(self, text: str) -> None:
        self.notes.append(text)
