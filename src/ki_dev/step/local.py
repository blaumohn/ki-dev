"""Allgemeine Übergabe für freie lokale Sitzungen ohne Bead.

Reiner Kern ohne Beads-Zugriff und Dateizugriff: Die Basis ist fester
Text, die Regeltexte (nur ``common``) kommen bereits ausgewählt.
Gemeinsam mit den Bead-Übergaben bleiben Leitlinienblock und
Basisgrenze.
"""

from __future__ import annotations

from collections.abc import Sequence

from ki_dev.flow.planning import NAME
from ki_dev.flow.templates import text
from ki_dev.ops.context.guidelines import (
    GuidelineSection,
    render_guideline_block,
)
from ki_dev.ops.context.limit import check_base_length


def render_local_handoff(
    guidelines: Sequence[GuidelineSection], base_max_chars: int
) -> str:
    """Feste Basis (Grenze gilt nur für sie), danach der gesonderte
    Leitlinienblock; zu lange Basis wird abgelehnt, nie gekürzt."""
    base = text(NAME, "local") + "\n"
    check_base_length(base, base_max_chars, ())
    return base + render_guideline_block(guidelines)
