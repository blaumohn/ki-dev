"""Gemeinsame Textregeln der Kontextbausteine. Ohne Abhängigkeit auf
Übergabe oder Leitlinien, damit beide sie nutzen, ohne einander zu
importieren."""

from __future__ import annotations

TEXTS = "turns"
"""Vorlagensatz der gemeinsamen Übergabetexte
(``flow/templates/turns``): Texte der Felder und Kontextbausteine, die
jeder Ablauf nutzen kann."""

# Nichtleerer Text als gemeinsamer Schema-Baustein (Technikleitlinie:
# einmal je Regel definiert und wiederverwendet).
NONEMPTY_TEXT_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "pattern": r"\S",
}


def one_line(value: object) -> str:
    """Einzeilig ohne Steuerzeichen (auch ANSI-Escapes)."""
    text = "".join(
        " " if ch.isspace() else ch
        for ch in str(value)
        if ch.isprintable() or ch.isspace()
    )
    return " ".join(text.split())
