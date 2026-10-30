"""Quellen des aufgezeichneten urq.6-Laufs: früher Abbruch.

Die Passagen nennen ihre Quellen mit ortsunabhängiger ID
(``bd:<Quellen-Bead>`` bzw. ``<agent>:<Sitzungs-ID>``) statt mit
lokalem Pfad. Die Auflösung ID → Datei (lokale Quellablage) ist noch
nicht umgesetzt (ki-dev-ablauf-xy78.2.1); bis dahin brechen
``scripts/urq6_*`` vor jedem Lesen absichtlich ab.
"""

from __future__ import annotations

from typing import NoReturn

QUELLABLAGE_FEHLT = (
    "Quelle nicht auflösbar, lokale Quellablage fehlt (Umsetzung "
    "ki-dev-ablauf-xy78.2.1, Entscheidung ki-dev-ablauf-guq)"
)


def abbruch_ohne_quellablage(feld: str, quelle: str) -> NoReturn:
    """Beendet mit Exitcode 1 und nennt Feldpfad und Quellen-ID."""
    raise SystemExit(f"{feld} = {quelle}: {QUELLABLAGE_FEHLT}")
