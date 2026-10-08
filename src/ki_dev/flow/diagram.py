"""Ablauf als Mermaid-Zustandsdiagramm, erzeugt aus der Quelle.

Diagramme in README und Doku werden hiermit erzeugt statt gepflegt;
ein Test vergleicht die eingebetteten Blöcke mit dieser Ausgabe. Die
Reihenfolge folgt der Datei, damit die Ausgabe deterministisch ist.

Eine Kante wird als ``event [cond] / actions`` beschriftet.
``@history`` erscheint als eigener Pseudozustand je wartendem Zustand,
weil Mermaid keinen History-Knoten kennt. ``without_escalations``
blendet Kanten mit ``escalation`` (Grenz- und Schutzhalte) aus; welche
das sind, entscheidet allein der Ablauf.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from ki_dev.flow.model import HISTORY, Flow, Transition


def render_mermaid(
    flow: Flow, *, without_escalations: bool = False
) -> str:
    transitions = [
        t
        for t in flow.transitions
        if not (without_escalations and t.escalation)
    ]
    used = _used_states(flow, transitions)
    lines = ["stateDiagram-v2", "    direction LR"]
    lines += [
        f'    state "{state}" as {_node(state)}'
        for state in used
        if _node(state) != state
    ]
    lines += [
        f'    state "{HISTORY}" as {_history(t.source)}'
        for t in _history_sources(transitions)
    ]
    lines.append(f"    [*] --> {_node(flow.start)}")
    lines += [
        f"    {_node(t.source)} --> {_target(t)}: {_label(t)}"
        for t in transitions
    ]
    lines += [
        f"    {_node(state)} --> [*]"
        for state in flow.final
        if state in used
    ]
    return "\n".join(lines) + "\n"


def _used_states(
    flow: Flow, transitions: list[Transition]
) -> list[str]:
    """Zustände an gezeigten Kanten, in Dateireihenfolge."""
    seen = {flow.start} | {t.source for t in transitions}
    seen |= {t.target for t in transitions if t.target != HISTORY}
    return [state for state in flow.states if state in seen]


def _history_sources(transitions: list[Transition]) -> list[Transition]:
    found: dict[str, Transition] = {}
    for t in transitions:
        if t.target == HISTORY:
            found.setdefault(t.source, t)
    return list(found.values())


def _node(state: str) -> str:
    """Mermaid-Bezeichner; Punkte sind dort nicht erlaubt."""
    return state.replace(".", "_")


def _history(source: str) -> str:
    return f"{_node(source)}_history"


def _target(t: Transition) -> str:
    return (
        _history(t.source) if t.target == HISTORY else _node(t.target)
    )


def _label(t: Transition) -> str:
    label = t.event
    if t.cond:
        label += f" [{', '.join(t.cond)}]"
    if t.actions:
        label += f" / {', '.join(t.actions)}"
    return label


# --- Einbettung in Markdown -------------------------------------------

_MARKER = re.compile(
    r"(<!-- ki-dev flow show (?P<name>[a-z_]+)"
    r"(?P<opt> --without-escalations)?"
    r" -->\n```mermaid\n)(?P<body>.*?)(```)",
    re.S,
)


def sync_diagrams(text: str, load: Callable[[str], Flow]) -> str:
    """Jeden Block nach ``<!-- ki-dev flow show NAME [OPTION] -->``
    durch die erzeugte Ausgabe ersetzen; die Marke ist der Befehl
    selbst."""

    def replace(match: re.Match[str]) -> str:
        diagram = render_mermaid(
            load(match["name"]), without_escalations=bool(match["opt"])
        )
        return match.group(1) + diagram + match.group(5)

    return _MARKER.sub(replace, text)


def diagram_markers(text: str) -> list[str]:
    """Namen der eingebetteten Abläufe in Dateireihenfolge."""
    return [match["name"] for match in _MARKER.finditer(text)]
