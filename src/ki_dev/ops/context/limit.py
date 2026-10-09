"""Reiner Kern der Basisgrenze für gerenderte Arbeitsübergaben.

Zählt Unicode-Zeichen (``len``) des tatsächlich gerenderten Basistexts
einschließlich Leerzeichen und Zeilenumbrüchen und rendert die
Diagnose. Keine Ein-/Ausgabe: Grenze und Anteile bekommt der Kern als
Daten; die Konfiguration liest ``limit_config``. Leitlinien- und
Prüfberichtsblock gehören nicht zur Basis und werden hier nie gesehen.
"""

from __future__ import annotations

from collections.abc import Sequence

CONFIG_TABLE = "tool.ki-dev.handoff"
CONFIG_KEY = "base_max_chars"
DEFAULT_BASE_MAX_CHARS = 4000

MAX_DIAGNOSIS_CHARS = 1000


class HandoffBaseTooLongError(ValueError):
    """Gerenderte Basisübergabe überschreitet die Grenze (Exit 2).

    ``fields`` sind die veränderlichen Anteile (Feldname, Zeichenzahl)
    ohne Rohtexte; feste Rollen- und Gemeinsamtexte zählen mit, stehen
    aber nicht darin.
    """

    def __init__(
        self,
        actual: int,
        limit: int,
        fields: Sequence[tuple[str, int]],
    ) -> None:
        self.actual = actual
        self.limit = limit
        self.fields = tuple(fields)
        super().__init__(self.diagnosis())

    def diagnosis(self, note: str = "") -> str:
        """Höchstens ``MAX_DIAGNOSIS_CHARS`` Zeichen; ``note`` ist ein
        kurzer fester Zusatz des Aufrufers."""
        head = (
            f"Basisübergabe zu lang: {self.actual} Zeichen, Grenze "
            f"{self.limit} ({CONFIG_TABLE}.{CONFIG_KEY}); keine "
            "Übergabe, keine Kürzung."
        )
        tail = f" {note}" if note else ""
        budget = MAX_DIAGNOSIS_CHARS - len(head) - len(tail)
        return head + _share_text(self.fields, budget) + tail


def check_base_length(
    text: str, limit: int, fields: Sequence[tuple[str, int]]
) -> None:
    """Gleich der Grenze ist zulässig, größer nicht."""
    actual = len(text)
    if actual > limit:
        raise HandoffBaseTooLongError(actual, limit, fields)


def _share_text(fields: Sequence[tuple[str, int]], budget: int) -> str:
    """Größte Anteile zuerst, soweit sie ins Budget passen."""
    ranked = [f"{name} {size}" for name, size in _largest_first(fields)]
    for count in range(len(ranked), 0, -1):
        text = _share_line(ranked, count)
        if len(text) <= budget:
            return text
    return ""


def _largest_first(
    fields: Sequence[tuple[str, int]],
) -> list[tuple[str, int]]:
    return sorted(fields, key=lambda item: -item[1])


def _share_line(ranked: list[str], count: int) -> str:
    omitted = len(ranked) - count
    marker = f" (+{omitted} weitere)" if omitted else ""
    return f" Anteile (Zeichen): {', '.join(ranked[:count])}{marker}."
