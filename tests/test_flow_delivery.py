"""Lieferablauf flow/delivery.toml: Bindung an die Maschine und
Begrenztheit.

Die Schleife ist eine Rückkante im Ablauf. Der Strukturtest unten zeigt
direkt an den Daten, dass jeder Zyklus ohne Menschen über eine Kante
läuft, die einen laufweiten Zähler erhöht; ``tests/machine`` beweist
dasselbe erschöpfend über den Zustandsraum.
"""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from ki_dev.flow.model import (
    WAIT_KIND,
    FlowError,
    load_flow,
    parse_flow,
    read_raw,
)
from ki_dev.runner.interpreter import bind
from ki_dev.runner.machine import DELIVERY_BOUND, Phase

DELIVERY = load_flow("delivery")
COUNTING = {
    "begin_task",
    "begin_correction",
    "retry_protocol",
    "retry_process",
}


def test_phase_names_exactly_the_states_of_the_flow():
    assert {phase.value for phase in Phase} == set(DELIVERY.states)


def test_every_cycle_without_a_human_consumes_a_counter():
    """Kanten ohne zählende Aktion und Halt bilden keinen Zyklus."""
    free = {
        (t.source, t.target)
        for t in DELIVERY.transitions
        if not COUNTING & set(t.actions)
        and DELIVERY.state(t.source).kind != WAIT_KIND
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
    binding = DELIVERY_BOUND.binding
    missing = dict(binding.guards)
    missing.pop("stagnation")
    with pytest.raises(FlowError, match="fehlt: stagnation"):
        bind(DELIVERY, replace(binding, guards=missing))
    extra = {**binding.actions, "zaubern": lambda state: state}
    with pytest.raises(FlowError, match="nicht deklariert: zaubern"):
        bind(DELIVERY, replace(binding, actions=extra))


def test_controller_operation_depends_on_reviewed_result():
    """Moore-Ausgabe: ohne geprüftes Ergebnis beauftragt die Maschine,
    mit Ergebnis urteilt der Controller."""
    (review, task) = DELIVERY.state("controller_step").operations
    assert (review.do, review.cond) == (
        "review",
        ("checked_result",),
    )
    assert (task.do, task.cond) == ("task", ())


def test_unguarded_candidate_must_come_last():
    raw = copy.deepcopy(read_raw("delivery"))
    index = next(
        i
        for i, t in enumerate(raw["transition"])
        if t["source"] == "controller_step"
        and t["event"] == "controller_task"
    )
    raw["transition"][index], raw["transition"][index + 1] = (
        raw["transition"][index + 1],
        raw["transition"][index],
    )
    with pytest.raises(FlowError, match="doppelter Übergang"):
        parse_flow(raw)

