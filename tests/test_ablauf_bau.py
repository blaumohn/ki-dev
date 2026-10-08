"""Bauablauf ablauf/bau.toml: Bindung an die Maschine und Begrenztheit.

Die Schleife ist eine Rückkante im Ablauf. Der Strukturtest unten zeigt
direkt an den Daten, dass jeder Zyklus ohne Menschen über eine Kante
läuft, die einen laufweiten Zähler erhöht; ``tests/machine`` beweist
dasselbe erschöpfend über den Zustandsraum.
"""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from ki_dev.ablauf.format import (
    WAIT_KIND,
    AblaufError,
    lade_ablauf,
    lies_rohdaten,
    parse_ablauf,
)
from ki_dev.ausfuehrer.interpreter import binde
from ki_dev.ausfuehrer.machine import BAU_GEBUNDEN, Phase
from tests.readme_diagramme import diagram_edges

BAU = lade_ablauf("bau")
COUNTING = {
    "task_beginnen",
    "korrektur_beginnen",
    "protokoll_wiederholen",
    "prozess_wiederholen",
}


def test_phase_names_exactly_the_states_of_the_flow():
    assert {phase.value for phase in Phase} == set(BAU.zustaende)


def test_every_cycle_without_a_human_consumes_a_counter():
    """Kanten ohne zählende Aktion und Halt bilden keinen Zyklus."""
    free = {
        (t.von, t.nach)
        for t in BAU.uebergaenge
        if not COUNTING & set(t.aktion)
        and BAU.zustand(t.von).art != WAIT_KIND
    }
    assert not _has_cycle(free)


def _has_cycle(edges: set[tuple[str, str]]) -> bool:
    graph: dict[str, set[str]] = {}
    for source, target in edges:
        graph.setdefault(source, set()).add(target)
    done: set[str] = set()

    def visit(node: str, path: set[str]) -> bool:
        if node in path:
            return True
        if node in done:
            return False
        found = any(
            visit(n, path | {node}) for n in graph.get(node, ())
        )
        done.add(node)
        return found

    return any(visit(node, set()) for node in graph)


def test_executor_must_speak_the_declared_vocabulary():
    bindung = BAU_GEBUNDEN.bindung
    missing = dict(bindung.waechter)
    missing.pop("stagnation")
    with pytest.raises(AblaufError, match="fehlt: stagnation"):
        binde(BAU, replace(bindung, waechter=missing))
    extra = {**bindung.aktionen, "zaubern": lambda state: state}
    with pytest.raises(AblaufError, match="nicht deklariert: zaubern"):
        binde(BAU, replace(bindung, aktionen=extra))


def test_controller_operation_depends_on_reviewed_result():
    """Moore-Ausgabe: ohne geprüftes Ergebnis beauftragt die Maschine,
    mit Ergebnis urteilt der Controller."""
    (review, auftrag) = BAU.zustand("controller_step").operationen
    assert (review.tue, review.wenn) == (
        "review",
        ("geprueftes_ergebnis",),
    )
    assert (auftrag.tue, auftrag.wenn) == ("task", ())


def test_unguarded_candidate_must_come_last():
    raw = copy.deepcopy(lies_rohdaten("bau"))
    index = next(
        i
        for i, t in enumerate(raw["uebergang"])
        if t["von"] == "controller_step"
        and t["bei"] == "controller_task"
    )
    raw["uebergang"][index], raw["uebergang"][index + 1] = (
        raw["uebergang"][index + 1],
        raw["uebergang"][index],
    )
    with pytest.raises(AblaufError, match="doppelter Übergang"):
        parse_ablauf(raw)


def test_readme_diagram_draws_only_edges_of_the_flow():
    """Die README zeigt den Hauptweg; jede Kante steht in bau.toml."""
    table = {(t.von, t.bei, t.nach) for t in BAU.uebergaenge}
    assert diagram_edges("bau") <= table
