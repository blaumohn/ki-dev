"""Auswahl von ``ki-dev step``: ``--step`` und ``--review-of``.

Bedienwörter der CLI, erzeugt aus den mitgelieferten Abläufen auf dem
Review-Muster (Phase = ihr Start, z. B. ``map``); dazu ``review``
(``done`` am Start des Ablaufs, :mod:`ki_dev.step.projection`).
"""

from __future__ import annotations

from enum import StrEnum

from ki_dev.flow.review_flow import review_flow_files

FLOWS = review_flow_files()
"""Phase → Ablauf (Dateiname unter ``flow/``)."""

REVIEW = "review"

DEFAULT_REVIEW = "implement"
"""Prüfgegenstand von ``--step review`` ohne ``--review-of``
(Bedienvorgabe der CLI)."""

Step = StrEnum(
    "Step", [(name.upper(), name) for name in (*FLOWS, REVIEW)]
)
ReviewTarget = StrEnum(
    "ReviewTarget", [(name.upper(), name) for name in FLOWS]
)
