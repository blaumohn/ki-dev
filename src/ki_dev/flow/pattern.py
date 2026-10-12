"""Topologie-Muster: wiederkehrende Phasen einmal beschreiben.

Ein Muster (``[pattern.NAME]``) ist ein parametrisierter, zusammen-
gesetzter Zustand im Sinne von Statecharts: lokale Zustände und Kanten
ohne Phasenbezug. Eine Phase (``[[phase]]``) setzt es ein und liefert
die Parameter. Der Lader expandiert vor allen Prüfungen zu flachen
Zuständen und Kanten; alles Weitere prüft und führt den flachen Ablauf.

Namensregeln, ohne Ausdrücke in Strings:

- Der lokale Zustand ``write`` heißt wie die Phase, jeder andere lokale
  Zustand ``PHASE.LOKAL`` (``map.review``).
- Ein Kantenziel ist ein lokaler Zustand, ``@next`` (der Parameter
  ``next`` der Phase) oder ein Name aus ``globals`` des Musters.
- ``actor`` der Phase ergänzt oder ersetzt die Vorgabe des Musters je
  lokalem Zustand; ``hint`` der Phase gilt je (lokalem Zustand,
  Ereignis) für die Kanten ohne eigenen Hinweis im Muster (so behält
  eine zweite Kante desselben Ereignisses, etwa PASS bei geändertem
  Stand, ihren Hinweis).
- ``template``, ``context``, ``require`` und ``role`` der Phase setzen
  je lokalem Zustand Rollenvorlage, Kontextbausteine, benötigte
  Bead-Felder und Rolle seiner einzigen Operation (der Übergabe); so
  trägt jede Phase ihre Übergabe als Daten.
- Eine Kante des Musters kann die Übergabe selbst bestimmen
  (``template``, ``context``: Nachricht am Übergang). ``@NAME`` als
  Vorlage nennt den Eintrag ``template.NAME`` der Phase, so wie
  ``@next`` den Parameter ``next``.
- ``extends`` übernimmt Zustände und Kanten eines anderen Musters und
  hängt eigene an. Ein neuer Schalter wird ein neues Muster, kein
  Bedingungsfeld (Leitlinie).

Expandierte Phasen stehen vor den ausdrücklich deklarierten Zuständen
und Kanten, in Deklarationsreihenfolge.
"""

from __future__ import annotations

from collections.abc import Mapping

NEXT = "@next"
REFERENCE = "@"
WRITE = "write"


class PatternError(ValueError):
    """Muster oder Phase verletzen die Namensregeln (Programmfehler)."""


def expand(raw: Mapping[str, object], where: str) -> dict[str, object]:
    """Flachen Ablauf aus ``pattern``/``phase`` erzeugen; ohne Phasen
    unverändert (bis auf entfernte leere Musterschlüssel)."""
    table = dict(raw)
    patterns = table.pop("pattern", {})
    phases = table.pop("phase", [])
    if not phases:
        return table
    states: list[dict] = []
    transitions: list[dict] = []
    for index, phase in enumerate(phases):
        label = f"{where}: phase.{index} ({phase['id']})"
        pattern = _resolve(patterns, phase["use"], label)
        new_states, new_transitions = _instantiate(
            pattern, phase, label
        )
        states += new_states
        transitions += new_transitions
    table["state"] = states + list(table.get("state", []))
    table["transition"] = transitions + list(
        table.get("transition", [])
    )
    return table


def _resolve(
    patterns: Mapping[str, dict], name: str, label: str
) -> dict[str, object]:
    """Muster mit aufgelöstem ``extends`` (Kette ohne Zyklus)."""
    seen: list[str] = []
    chain: list[dict] = []
    current: str | None = name
    while current is not None:
        if current in seen:
            raise PatternError(
                f"{label}: extends-Zyklus über {current}"
            )
        if current not in patterns:
            raise PatternError(f"{label}: unbekanntes Muster {current}")
        seen.append(current)
        chain.append(patterns[current])
        current = patterns[current].get("extends")
    resolved: dict[str, object] = {
        "globals": [],
        "state": [],
        "transition": [],
    }
    for pattern in reversed(chain):
        resolved["globals"] += pattern.get("globals", [])
        resolved["state"] += pattern.get("state", [])
        resolved["transition"] += pattern.get("transition", [])
    return resolved


def _instantiate(
    pattern: Mapping[str, list], phase: Mapping[str, object], label: str
) -> tuple[list[dict], list[dict]]:
    phase_id = str(phase["id"])
    locals_ = [str(state["local"]) for state in pattern["state"]]
    actors = dict(phase.get("actor", {}))
    hints = {
        local: dict(events)
        for local, events in phase.get("hint", {}).items()
    }
    turns = _turns(phase)
    _check_overrides(locals_, actors, hints, pattern, label)
    referenced = {
        str(item["template"]).removeprefix(REFERENCE)
        for item in pattern["transition"]
        if str(item.get("template", "")).startswith(REFERENCE)
    }
    operations = dict(phase.get("operation", {}))
    for local in operations:
        if local not in locals_:
            raise PatternError(f"{label}: operation.{local}: unbekannt")
    for local in turns:
        if local not in locals_ and local not in referenced:
            raise PatternError(
                f"{label}: template/context.{local}: unbekannt"
            )
    states = [
        _state(
            state,
            phase_id,
            actors.get(state["local"]),
            {
                **turns.get(str(state["local"]), {}),
                **(
                    {"do": operations[state["local"]]}
                    if state["local"] in operations
                    else {}
                ),
            },
            label,
        )
        for state in pattern["state"]
    ]
    transitions = [
        _transition(
            item, phase, locals_, pattern["globals"], hints, label
        )
        for item in pattern["transition"]
    ]
    return states, transitions


def _state_id(phase_id: str, local: str) -> str:
    return phase_id if local == WRITE else f"{phase_id}.{local}"


def _turns(
    phase: Mapping[str, object],
) -> dict[str, dict[str, object]]:
    """Übergabe-Parameter je lokalem Zustand (template, context,
    require, role)."""
    turns: dict[str, dict[str, object]] = {}
    for key in ("template", "context", "require", "role"):
        for local, value in dict(phase.get(key, {})).items():
            turns.setdefault(local, {})[key] = value
    return turns


def _state(
    item: Mapping,
    phase_id: str,
    actor: object,
    turn: Mapping[str, object],
    label: str,
) -> dict:
    state = {
        key: value for key, value in item.items() if key != "local"
    }
    state["id"] = _state_id(phase_id, str(item["local"]))
    if actor is not None:
        state["actor"] = actor
    if turn:
        operations = list(state.get("operation", ()))
        if len(operations) != 1:
            raise PatternError(
                f"{label}: template/context.{item['local']}: braucht "
                "genau eine Operation"
            )
        state["operation"] = [{**operations[0], **turn}]
    return state


def _transition(
    item: Mapping,
    phase: Mapping[str, object],
    locals_: list[str],
    globals_: list[str],
    hints: Mapping[str, Mapping[str, str]],
    label: str,
) -> dict:
    phase_id = str(phase["id"])
    source, target = str(item["source"]), str(item["target"])
    if source not in locals_:
        raise PatternError(
            f"{label}: unbekannte lokale Quelle {source}"
        )
    transition = dict(item)
    transition["source"] = _state_id(phase_id, source)
    transition["target"] = _target(
        phase, target, locals_, globals_, label
    )
    hint = hints.get(source, {}).get(str(item["event"]))
    if hint is not None and "hint" not in item:
        transition["hint"] = hint
    template = str(item.get("template", ""))
    if template.startswith(REFERENCE):
        name = template.removeprefix(REFERENCE)
        named = dict(phase.get("template", {}))
        if name not in named:
            raise PatternError(f"{label}: template.{name} fehlt")
        transition["template"] = named[name]
    return transition


def _target(
    phase: Mapping[str, object],
    target: str,
    locals_: list[str],
    globals_: list[str],
    label: str,
) -> str:
    if target == NEXT:
        if "next" not in phase:
            raise PatternError(f"{label}: {NEXT} ohne next")
        return str(phase["next"])
    if target in locals_:
        return _state_id(str(phase["id"]), target)
    if target in globals_:
        return target
    raise PatternError(f"{label}: unbekanntes Ziel {target}")


def _check_overrides(
    locals_: list[str],
    actors: Mapping[str, object],
    hints: Mapping[str, Mapping[str, str]],
    pattern: Mapping[str, list],
    label: str,
) -> None:
    """Parameter für unbekannte Zustände oder Kanten sind Tippfehler,
    keine stillen Leerläufe."""
    for local in actors:
        if local not in locals_:
            raise PatternError(f"{label}: actor.{local}: unbekannt")
    edges = {
        (str(item["source"]), str(item["event"]))
        for item in pattern["transition"]
    }
    for local, events in hints.items():
        for event in events:
            if (local, event) not in edges:
                raise PatternError(
                    f"{label}: hint.{local}.{event}: keine Kante"
                )
