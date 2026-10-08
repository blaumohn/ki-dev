"""Erschoepfender Beweis der Begrenztheit ueber den Zustandsraum.

Der V0-Automat ist unter festen Grenzen endlich. Deshalb laesst sich
die Kerninvariante aus Quellen-Bead ki-dev-ablauf-9p4a, Planerausgabe 18, nicht
nur stichprobenartig, sondern vollstaendig pruefen: der gesamte
erreichbare Graph wird aufgezaehlt und danach als Ganzes beurteilt.

Dass diese Aufzaehlung ueberhaupt terminiert, ist bereits der Nachweis,
dass kein aktiver Zyklus unbegrenzt wiederholbar ist.
"""

from __future__ import annotations

from collections import Counter as Multiset

from ki_dev.ausfuehrer.machine import (
    STOPPED_PHASES,
    ControllerPass,
    Event,
    IntegrationCompleted,
    InvalidTransition,
    MachineState,
    Phase,
    advance,
)

from .conftest import EVENT_POOL, TIGHT_LIMITS

_Edge = tuple[MachineState, Event, MachineState]


def _outgoing(state: MachineState) -> list[_Edge]:
    """Alle angenommenen Uebergaenge genau eines Zustands."""
    if state.is_stopped:
        return []
    edges: list[_Edge] = []
    for event in EVENT_POOL:
        try:
            target = advance(state, event, TIGHT_LIMITS).state
        except InvalidTransition:
            continue
        edges.append((state, event, target))
    return edges


def _explore() -> tuple[set[MachineState], list[_Edge]]:
    """Zaehle alle erreichbaren Zustaende und Uebergaenge auf."""
    start = MachineState(phase=Phase.START)
    seen = {start}
    pending = [start]
    edges: list[_Edge] = []
    while pending:
        outgoing = _outgoing(pending.pop())
        edges.extend(outgoing)
        fresh = {target for _, _, target in outgoing} - seen
        seen |= fresh
        pending.extend(fresh)
    return seen, edges


_STATES, _EDGES = _explore()


def test_state_space_stays_finite():
    assert _STATES
    assert len(_STATES) < 5000
    assert len(_EDGES) < 20000


def test_every_phase_is_reachable():
    reached = {state.phase for state in _STATES}
    assert reached == set(Phase)


def test_no_free_cycle_exists():
    """Kernaussage: kein Zyklus ohne laufweiten Ressourcenverbrauch.

    Massgeblich ist allein ``run_total``. Das TASK-lokale
    ``changes_round`` darf ein neuer TASK zuruecksetzen und taugt
    deshalb nicht als Abstiegsmass.
    """
    free = [
        (source, target)
        for source, _, target in _EDGES
        if source.counters.run_total == target.counters.run_total
    ]
    assert free
    assert not _has_cycle(free)


def _has_cycle(edges: list[tuple[MachineState, MachineState]]) -> bool:
    """Pruefe per Kahn-Verfahren, ob der Teilgraph zyklisch ist."""
    successors: dict[MachineState, list[MachineState]] = {}
    indegree: Multiset[MachineState] = Multiset()
    nodes: set[MachineState] = set()
    for source, target in edges:
        successors.setdefault(source, []).append(target)
        indegree[target] += 1
        nodes.update((source, target))
    ready = [node for node in nodes if indegree[node] == 0]
    removed = 0
    while ready:
        node = ready.pop()
        removed += 1
        ready.extend(_released(successors.get(node, ()), indegree))
    return removed != len(nodes)


def _released(
    targets: tuple[MachineState, ...] | list[MachineState],
    indegree: Multiset[MachineState],
) -> list[MachineState]:
    """Nachfolger, deren letzte eingehende Kante entfernt wurde."""
    freed = []
    for target in targets:
        indegree[target] -= 1
        if indegree[target] == 0:
            freed.append(target)
    return freed


def test_every_reachable_state_can_still_stop():
    """Kein erreichbarer Zustand ist eine Sackgasse."""
    predecessors: dict[MachineState, set[MachineState]] = {}
    for source, _, target in _EDGES:
        predecessors.setdefault(target, set()).add(source)
    can_stop = {
        state for state in _STATES if state.phase in STOPPED_PHASES
    }
    pending = list(can_stop)
    while pending:
        fresh = predecessors.get(pending.pop(), set()) - can_stop
        can_stop |= fresh
        pending.extend(fresh)
    assert can_stop == _STATES


def test_passed_entered_only_by_integration():
    entries = {
        (source.phase, type(event))
        for source, event, target in _EDGES
        if target.phase is Phase.PASSED
    }
    assert entries == {
        (Phase.FAST_FORWARD_INTEGRATE, IntegrationCompleted)
    }


def test_pass_never_lands_on_passed():
    targets = {
        target.phase
        for _, event, target in _EDGES
        if isinstance(event, ControllerPass)
    }
    assert targets == {Phase.FREEZE_REVIEWED_RESULT}


def test_rounds_reset_only_on_a_new_task():
    """Ein Rueckgang der Runden kostet stets einen Worker-Versuch."""
    resets = [
        (source, target)
        for source, _, target in _EDGES
        if target.counters.changes_round < source.counters.changes_round
    ]
    assert resets
    for source, target in resets:
        assert target.counters.changes_round == 0
        assert (
            target.counters.worker_attempt
            > source.counters.worker_attempt
        )


def test_round_budget_never_exceeds_its_limit():
    assert all(
        state.counters.changes_round <= TIGHT_LIMITS.changes_rounds
        for state in _STATES
    )


def test_no_judgement_without_checkpoint():
    """PASS und CHANGES setzen einen echten Worker-Schritt voraus."""
    reviewable = [s for s in _STATES if s.checkpointed_result]
    assert reviewable
    assert all(s.counters.worker_attempt >= 1 for s in reviewable)
    frozen = [
        source
        for source, _, target in _EDGES
        if target.phase is Phase.FREEZE_REVIEWED_RESULT
    ]
    assert frozen
    assert all(source.checkpointed_result for source in frozen)
