"""Hypothesis-Eigenschaften der Begrenztheit des V0-Automaten.

Geprueft wird die Kerninvariante aus Quellen-Bead ki-dev-ablauf-9p4a,
Planerausgabe 18:

    Kein aktiver Zyklus ist unbegrenzt wiederholbar. Jeder
    wiederholbare Weg verbraucht eine monoton fortschreitende, nach
    oben begrenzte Ressource oder endet in einem wartenden bzw.
    terminalen Zustand.

Die Ereignisse werden phasenbewusst gezogen. Rein gleichverteiltes
Ziehen aus allen Ereignistypen bleibt fast immer in den ersten beiden
Phasen haengen und wuerde die Eigenschaft nahezu leer pruefen. Ein
Zehntel der Zuege bleibt trotzdem beliebig, damit auch abgewiesene
Uebergaenge vorkommen.
"""

from __future__ import annotations

from itertools import pairwise

from hypothesis import given, settings
from hypothesis import strategies as st

from ki_dev.runner.machine import (
    STOPPED_PHASES,
    Event,
    InvalidTransition,
    MachineState,
    Phase,
    advance,
)

from .conftest import EVENT_POOL, TIGHT_LIMITS, TRANSITIONS

_MAX_TURNS = 60

_BY_TYPE: dict[type[Event], list[Event]] = {}
for _event in EVENT_POOL:
    _BY_TYPE.setdefault(type(_event), []).append(_event)

_PLAUSIBLE: dict[Phase, list[Event]] = {
    phase: [
        event for event_type in row for event in _BY_TYPE[event_type]
    ]
    for phase, row in TRANSITIONS.items()
}

# Nur die laufweit monotonen Grenzen; changes_round gehoert zum
# jeweiligen TASK und wird von einem neuen TASK zurueckgesetzt.
_BUDGET = (
    TIGHT_LIMITS.protocol_attempts
    + TIGHT_LIMITS.worker_attempts
    + TIGHT_LIMITS.process_retries
)


def _draw_event(data, phase: Phase) -> Event:
    """Meist ein hier plausibles, gelegentlich ein beliebiges Zug."""
    candidates = _PLAUSIBLE.get(phase)
    if candidates is None or data.draw(st.integers(0, 9)) == 0:
        return data.draw(st.sampled_from(EVENT_POOL))
    return data.draw(st.sampled_from(candidates))


def _walk(data) -> list[MachineState]:
    """Fahre einen Lauf und sammle nur angenommene Zustaende."""
    state = MachineState(phase=Phase.START)
    states = [state]
    for _ in range(_MAX_TURNS):
        if state.is_stopped:
            break
        event = _draw_event(data, state.phase)
        try:
            state = advance(state, event, TIGHT_LIMITS).state
        except InvalidTransition:
            continue
        states.append(state)
    return states


@given(st.data())
@settings(max_examples=400)
def test_revisit_consumes_a_limit(data):
    """Massgeblich ist ``run_total``, nicht das TASK-Rundenbudget."""
    seen: dict[Phase, int] = {}
    for state in _walk(data):
        total = state.counters.run_total
        previous = seen.get(state.phase)
        assert previous is None or total > previous, (
            f"{state.phase} ohne Ressourcenverbrauch erneut erreicht"
        )
        seen[state.phase] = total


@given(st.data())
@settings(max_examples=400)
def test_counters_grow_within_budget(data):
    totals = [state.counters.run_total for state in _walk(data)]
    assert totals == sorted(totals)
    assert max(totals) <= _BUDGET


@given(st.data())
@settings(max_examples=400)
def test_round_budget_stays_within_its_limit(data):
    """Das TASK-lokale Budget darf sinken, aber nie ueberlaufen."""
    for state in _walk(data):
        assert state.counters.changes_round >= 0
        assert (
            state.counters.changes_round <= TIGHT_LIMITS.changes_rounds
        )


@given(st.data())
@settings(max_examples=400)
def test_run_stops_or_has_budget_left(data):
    states = _walk(data)
    final = states[-1]
    if final.phase in STOPPED_PHASES:
        return
    assert final.counters.run_total <= _BUDGET
    assert len(states) <= (_BUDGET + 1) * len(Phase)


@given(st.data())
@settings(max_examples=400)
def test_passed_only_after_integration(data):
    for previous, current in pairwise(_walk(data)):
        if current.phase is Phase.PASSED:
            assert previous.phase is Phase.FAST_FORWARD_INTEGRATE


@given(st.data())
@settings(max_examples=400)
def test_judgement_follows_a_checkpoint(data):
    """Ohne Worker-Schritt gibt es weder PASS-Weg noch PASSED."""
    for state in _walk(data):
        if state.phase in {
            Phase.FREEZE_REVIEWED_RESULT,
            Phase.PASSED,
        }:
            assert state.counters.worker_attempt >= 1
