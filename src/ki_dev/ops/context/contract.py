"""Gemeinsame Begriffe von ``ki-dev step``: Schritte, Prüfgegenstände,
Textregeln. Ohne Abhängigkeit auf Übergabe oder Leitlinien, damit beide
sie nutzen, ohne einander zu importieren."""

from __future__ import annotations

from enum import StrEnum

# Nichtleerer Text als gemeinsamer Schema-Baustein (Technikleitlinie:
# einmal je Regel definiert und wiederverwendet).
NONEMPTY_TEXT_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "pattern": r"\S",
}


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


def one_line(value: object) -> str:
    """Einzeilig ohne Steuerzeichen (auch ANSI-Escapes)."""
    text = "".join(
        " " if ch.isspace() else ch
        for ch in str(value)
        if ch.isprintable() or ch.isspace()
    )
    return " ".join(text.split())
