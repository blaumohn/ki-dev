"""Vorlagen der Rollen- und Folgetexte je Ablauf.

Texte für Menschen und Agenten stehen als Dateien unter
``flow/templates/<ABLAUF>/<NAME>.txt``, nicht als Python-Konstanten.
Platzhalter füllt :func:`render` mit ``string.Template.substitute``:
ein fehlender Wert ist ein Fehler, nie eine stille Lücke. Vorlagen
enthalten keine Bedingungen; optionale Blöcke setzt der Code zusammen.
"""

from __future__ import annotations

from functools import cache
from importlib.resources import files
from string import Template


@cache
def text(flow: str, name: str) -> str:
    """Vorlage ohne den abschließenden Zeilenumbruch der Datei."""
    resource = files("ki_dev.flow").joinpath(
        "templates", flow, f"{name}.txt"
    )
    return resource.read_text(encoding="utf-8").removesuffix("\n")


def lines(flow: str, name: str) -> tuple[str, ...]:
    return tuple(text(flow, name).split("\n"))


def render(flow: str, name: str, **values: object) -> str:
    return Template(text(flow, name)).substitute(values)
