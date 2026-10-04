"""Konfigurationsorte der ki-dev-Befehle als Daten.

Jedes zuständige Modul definiert seinen Ort selbst (eine maßgebliche
Definition); ``ki-dev config`` sammelt die Angaben nur ein. Das Modul
importiert keine anderen ki_dev-Module, damit jedes Modul den Typ ohne
Rückkopplung nutzen kann.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ConfigSource:
    """Wo ein Befehl seine Konfiguration liest.

    ``path`` ist relativ zum aktuellen Verzeichnis oder absolut;
    ``None`` heißt, der Ort wird je Aufruf angegeben (``location``
    nennt dann die Option).
    """

    command: str
    location: str
    section: str = ""
    path: Path | None = None
