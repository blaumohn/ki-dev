"""Kanten eines markierten Mermaid-Zustandsdiagramms der README.

Ein Diagramm steht direkt nach ``<!-- diagramm:NAME -->``. Die Marke
macht den Test unabhängig von Reihenfolge und Anzahl der Diagramme.
"""

from __future__ import annotations

import re
from pathlib import Path

README = Path(__file__).parent.parent / "README.md"


def diagram_edges(name: str) -> set[tuple[str, str, str]]:
    """(von, bei, nach) je beschrifteter Kante, Aliasse aufgelöst."""
    text = README.read_text(encoding="utf-8")
    marker = f"<!-- diagramm:{name} -->"
    assert marker in text, f"README ohne {marker}"
    block = text.split(marker, 1)[1].split("```mermaid", 1)[1]
    block = block.split("```", 1)[0]
    pattern = r'^\s*state "([^"]+)" as (\S+)$'
    aliases = {
        alias: label
        for label, alias in re.findall(pattern, block, re.M)
    }
    edges = re.findall(r"^\s*(\S+) --> (\S+): (\S+)$", block, re.M)
    assert edges, f"Diagramm {name} ohne beschriftete Kanten"
    return {
        (
            aliases.get(source, source),
            event,
            aliases.get(target, target),
        )
        for source, target, event in edges
    }
