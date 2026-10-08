"""Allgemeine Übergabe für freie lokale Sitzungen ohne Bead.

Reiner Kern ohne Beads-Zugriff und Dateizugriff: Die Basis ist fester
Text, die Regeltexte (nur ``common``) kommen bereits ausgewählt.
Gemeinsam mit den Bead-Übergaben bleiben Leitlinienblock und
Basisgrenze.
"""

from __future__ import annotations

from collections.abc import Sequence

from ki_dev.step.guidelines import (
    GuidelineSection,
    render_guideline_block,
)
from ki_dev.step.limit import check_base_length

_LOCAL_BASE = (
    "Schritt: local",
    "",
    "Freie lokale Sitzung ohne Bead: Es gibt keine Beads-ID und keinen",
    "Auftrag aus Beads, und die Übergabe braucht weder Bead noch",
    "Datenbankverbindung. Arbeite nach der Anweisung des Menschen und",
    "dem tatsächlichen Arbeitsstand; lies gezielt. Melde konkrete",
    "fehlende Voraussetzungen, statt zu raten.",
    "",
    "Es ist keine Rolle eines Handoff-Schritts gewählt: Beads-Status",
    "nur lesen. Lesebefehle und Rollenrechte stehen im Block unten.",
    "",
    "Hinweis für den Menschen: Für einen Beads-Auftrag stattdessen",
    "`ki-dev step BEAD_ID --step STEP` verwenden.",
)


def render_local_handoff(
    guidelines: Sequence[GuidelineSection], base_max_chars: int
) -> str:
    """Feste Basis (Grenze gilt nur für sie), danach der gesonderte
    Leitlinienblock; zu lange Basis wird abgelehnt, nie gekürzt."""
    base = "\n".join(_LOCAL_BASE) + "\n"
    check_base_length(base, base_max_chars, ())
    return base + render_guideline_block(guidelines)
