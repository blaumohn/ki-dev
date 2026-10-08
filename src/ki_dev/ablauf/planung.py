"""Planungsablauf (``planung.toml``): Review-Semantik, Übergaben.

Fachliche Sicht auf den allgemeinen
:class:`~ki_dev.ablauf.format.Ablauf` für die Phasen map, graph,
materialize und build: welche Befundklasse ein Review-Ereignis ist,
welches Urteil daraus folgt und welche Folgeschritte der Mensch als
Bote (Adapter ``manuell``, ``ki-dev step``) erhält.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from ki_dev.ablauf.format import (
    Ablauf,
    AblaufError,
    Uebergang,
    lade_ablauf,
)

NAME = "planung"
FILE_NAME = f"{NAME}.toml"
PASS = "PASS"


@dataclass(frozen=True)
class Planungsablauf:
    ablauf: Ablauf

    def outgoing(self, state: str) -> tuple[Uebergang, ...]:
        return self.ablauf.ausgehend(state)

    def review_event(self, classes: Iterable[str]) -> str:
        """PASS ohne Befunde, sonst die stärkste Klasse nach vorrang."""
        found = set(classes)
        unknown = found - set(self.ablauf.vorrang)
        if unknown:
            raise AblaufError(
                f"unbekannte Befundklasse: {', '.join(sorted(unknown))}"
            )
        for name in self.ablauf.vorrang:
            if name in found:
                return name
        return PASS

    def verdict(self, event: str) -> str:
        """Review-Urteil zu PASS oder einer Befundklasse."""
        if event == PASS:
            return PASS
        if event not in self.ablauf.befundklassen:
            raise AblaufError(f"kein Review-Ereignis: {event}")
        return self.ablauf.befundklassen[event].urteil

    def events_for_verdict(self, verdict: str) -> tuple[str, ...]:
        """Review-Ereignisse zu einem Urteil: PASS selbst, sonst die
        Befundklassen mit diesem Urteil (in Vorrangreihenfolge)."""
        if verdict == PASS:
            return (PASS,)
        events = tuple(
            name
            for name in self.ablauf.vorrang
            if self.ablauf.befundklassen[name].urteil == verdict
        )
        if not events:
            raise AblaufError(f"kein Urteil des Ablaufs: {verdict}")
        return events

    def hint_lines(
        self,
        state: str,
        bead: str,
        events: Iterable[str] | None = None,
    ) -> list[str]:
        """Übergabe an den Menschen als Boten: Folgeschritte aus dem
        Ablauf mit eingesetzter Bead-ID; ``events`` beschränkt sie auf
        die Übergänge eines Urteils."""
        wanted = None if events is None else set(events)
        lines = [
            f"Hinweis für den Menschen: Zustand {state}; Folgeschritte "
            f"laut {FILE_NAME} (Adapter manuell, du trägst sie weiter):"
        ]
        for transition in self.outgoing(state):
            if wanted is not None and transition.bei not in wanted:
                continue
            command = (transition.befehl or "").replace("{bead}", bead)
            lines.append(
                f"- {transition.bei} → {transition.nach}: {command}"
            )
        return lines

    def class_lines(self) -> list[str]:
        """Befundklassen für Review-Rollen, in Vorrangreihenfolge."""
        classes = self.ablauf.befundklassen
        parts = [
            f"{name} = {classes[name].text} ({classes[name].urteil})"
            for name in self.ablauf.vorrang
        ]
        return [
            "Befundklassen: " + "; ".join(parts) + ".",
            "Nenne je Befund seine Klasse; das Urteil folgt der "
            f"stärksten Klasse ({' > '.join(self.ablauf.vorrang)}), "
            "ohne Befund PASS.",
        ]


def lade_planungsablauf() -> Planungsablauf:
    """Mitgelieferten Planungsablauf laden und prüfen; er muss
    Befundklassen und für jeden Übergang einen Befehl tragen."""
    ablauf = lade_ablauf(NAME)
    if not ablauf.befundklassen:
        raise AblaufError(f"{FILE_NAME}: befundklasse fehlt")
    for index, transition in enumerate(ablauf.uebergaenge):
        if transition.befehl is None:
            raise AblaufError(
                f"{FILE_NAME}: uebergang.{index}.befehl fehlt"
            )
    return Planungsablauf(ablauf)
