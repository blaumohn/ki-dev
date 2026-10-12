"""Auswahl von ``ki-dev step``: ``--step`` und ``--review-of``.

Bedienwörter der CLI; welcher Ablauf dazu gehört, bestimmt
:func:`ki_dev.step.options.flow_name`."""

from __future__ import annotations

from enum import StrEnum


class Step(StrEnum):
    MAP = "map"
    GRAPH = "graph"
    MATERIALIZE = "materialize"
    IMPLEMENT = "implement"
    REVIEW = "review"


class ReviewTarget(StrEnum):
    """Prüfgegenstand von ``Step.REVIEW``; nur dieser wertet es aus.

    Fehlt ``review_target`` bei ``Step.REVIEW``, bleibt das
    Verhalten die bisherige Umsetzungs-Review (Rückwärtskompatibilität
    von ``--step review`` ohne ``--review-of``).
    """

    MAP = "map"
    GRAPH = "graph"
    MATERIALIZE = "materialize"
    IMPLEMENT = "implement"
