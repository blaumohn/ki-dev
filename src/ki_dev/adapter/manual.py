"""Adapter ``manual``: der Mensch als Bote zwischen ki-dev und einer
Agentensitzung.

Der Bote trägt die Eingabe, die ki-dev sonst selbst an Claude oder
Codex schicken würde, in eine Sitzung seiner Wahl und legt deren
formale Antwort zurück. Er entscheidet nichts: die Antwort durchläuft
dieselbe Prüfung wie bei jedem anderen Adapter (z. B. das JSON-Urteil
des Reviews). Entscheider ist der Mensch nur in den Zuständen der Art
``warten`` des Ablaufs, nicht hier.

Fehlt die Antwort noch, schreibt der Adapter die Eingabe in den
Posteingang und meldet :class:`ManualInputPending`. Das ist ein Halt des
Ausführers, kein Ablaufzustand: der Lauf bleibt im selben Zustand, die
Operation bleibt offen und läuft nach ``ki-dev run resume`` mit der
Antwort weiter.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ki_dev.adapter.contract import (
    BuildReport,
    BuildRequest,
    ReviewRequest,
)
from ki_dev.adapter.prompts import (
    build_prompt,
    review_prompt,
)

NAME = "manual"


class ManualInputPending(Exception):
    """Die Eingabe liegt bereit; die Antwort des Boten fehlt noch."""

    def __init__(self, ask: Path, answer: Path) -> None:
        self.ask = ask
        self.answer = answer
        super().__init__(
            f"Eingabe {ask} in eine Sitzung tragen, Antwort nach "
            f"{answer} legen, dann `ki-dev run resume` aufrufen"
        )


@dataclass(frozen=True)
class ManualRelay:
    """Bau- und Review-Rolle über einen menschlichen Boten."""

    inbox: Path
    role: str

    def build(self, request: BuildRequest) -> BuildReport:
        return BuildReport(self._relay(request, build_prompt(request)))

    def review(self, request: ReviewRequest) -> str:
        return self._relay(request, review_prompt(request))

    def _relay(
        self, request: BuildRequest | ReviewRequest, prompt: str
    ) -> str:
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]
        key = f"r{request.round_id:04d}-{self.role}-{digest}"
        ask = self.inbox / f"{key}.eingabe.md"
        answer = self.inbox / f"{key}.antwort.md"
        if answer.is_file():
            text = answer.read_text(encoding="utf-8")
            if text.strip():
                return text
        self.inbox.mkdir(parents=True, exist_ok=True)
        ask.write_text(prompt, encoding="utf-8")
        raise ManualInputPending(ask, answer)
