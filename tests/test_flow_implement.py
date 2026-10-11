"""Umsetzungsablauf flow/implement.toml: Bindung an die Maschine und
Begrenztheit.

Die Schleife ist eine Rückkante im Ablauf. Der Strukturtest unten zeigt
direkt an den Daten, dass jeder Zyklus ohne Menschen über eine Kante
läuft, die einen laufweiten Zähler erhöht; ``tests/machine`` beweist
dasselbe erschöpfend über den Zustandsraum.
"""

from __future__ import annotations

import copy

import pytest

from ki_dev.flow.model import (
    WAIT_KIND,
    FlowError,
    load_flow,
    parse_flow,
    read_raw,
)
from ki_dev.fsm import FsmError, bind
from ki_dev.runner.machine import ImplementModel, Phase

IMPLEMENT = load_flow("implement")
COUNTING = {
    "begin_task",
    "begin_correction",
    "retry_protocol",
    "retry_process",
}


def test_phase_names_exactly_the_states_of_the_flow():
    assert {phase.value for phase in Phase} == set(IMPLEMENT.states)


def test_every_cycle_without_a_human_consumes_a_counter():
    """Kanten ohne zählende Aktion und Halt bilden keinen Zyklus."""
    free = {
        (t.source, t.target)
        for t in IMPLEMENT.transitions
        if not COUNTING & set(t.actions)
        and IMPLEMENT.state(t.source).kind != WAIT_KIND
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
    class Missing(ImplementModel):
        stagnation = None

    with pytest.raises(FsmError, match="fehlt: stagnation"):
        bind(IMPLEMENT.statechart, Missing)

    class Extra(ImplementModel):
        def zaubern(self) -> None: ...

    with pytest.raises(FsmError, match="ungenutzt: zaubern"):
        bind(IMPLEMENT.statechart, Extra)


def test_controller_operation_depends_on_reviewed_result():
    """Moore-Ausgabe: ohne geprüftes Ergebnis beauftragt die Maschine,
    mit Ergebnis urteilt der Controller."""
    (review, task) = IMPLEMENT.state("controller_step").operations
    assert (review.do, review.cond) == (
        "review",
        ("checked_result",),
    )
    assert (task.do, task.cond) == ("task", ())


def test_unguarded_candidate_must_come_last():
    raw = copy.deepcopy(read_raw("implement"))
    edges = raw["statechart"]["states"]["active"]["states"][
        "controller_step"
    ]["transitions"]
    edges[0], edges[1] = edges[1], edges[0]
    with pytest.raises(FlowError, match="doppelter Übergang"):
        parse_flow(raw)


def test_fact_layer_names_exactly_the_innermost_states():
    raw = copy.deepcopy(read_raw("implement"))
    del raw["state"]["checkpoint"]
    with pytest.raises(FlowError, match="fehlt: checkpoint"):
        parse_flow(raw)


def test_view_is_derived_from_the_statechart():
    """Kanten des Elternzustands gelten für jeden Arbeitszustand und
    folgen dessen eigenen; ``raise`` wird zur Eskalation."""
    stopped = [
        t
        for t in IMPLEMENT.transitions
        if t.event == "execution_stopped"
    ]
    assert {t.source for t in stopped} == set(raw_active_states())
    assert {t.escalation for t in stopped} == {"execution_guard"}
    (resume,) = IMPLEMENT.candidates(
        "paused_interactive", "resume_requested"
    )
    assert resume.target == "@history"


def raw_active_states() -> list[str]:
    return list(
        read_raw("implement")["statechart"]["states"]["active"]["states"]
    )

