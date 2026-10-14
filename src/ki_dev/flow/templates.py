"""Vorlagen der Rollen- und Folgetexte je Ablauf.

Texte für Menschen und Agenten stehen als Dateien unter
``templates/<SATZ>/<NAME>.txt`` neben der Ablaufdatei, nicht als
Python-Konstanten. Ohne ``root`` gilt das Gerüst (``ki_dev/flow``);
ein Paket nennt seine Wurzel (``Flow.root``), ein Rückfall auf das
Gerüst findet nicht statt. Platzhalter füllt :func:`render` mit
``string.Template.substitute``: ein fehlender Wert ist ein Fehler, nie
eine stille Lücke. Vorlagen enthalten keine Bedingungen; optionale
Blöcke setzt der Code zusammen.
"""

from __future__ import annotations

from functools import cache
from importlib.resources import files
from importlib.resources.abc import Traversable
from string import Template

SHIPPED: Traversable = files("ki_dev.flow")


@cache
def text(flow: str, name: str, root: Traversable = SHIPPED) -> str:
    """Vorlage ohne den abschließenden Zeilenumbruch der Datei."""
    resource = root.joinpath("templates", flow, f"{name}.txt")
    return resource.read_text(encoding="utf-8").removesuffix("\n")


def lines(
    flow: str, name: str, root: Traversable = SHIPPED
) -> tuple[str, ...]:
    return tuple(text(flow, name, root).split("\n"))


def render(
    flow: str, name: str, root: Traversable = SHIPPED, **values: object
) -> str:
    return Template(text(flow, name, root)).substitute(values)
