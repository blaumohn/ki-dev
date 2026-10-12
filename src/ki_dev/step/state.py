"""Laufzustand je Bead für ``ki-dev step`` (lokal, nicht in bd/Dolt).

Der Zustand ist der Datensatz des Ausführers
(:mod:`ki_dev.runner.planning`) für den zuletzt gelaufenen step-Ablauf
(``flow/step/<ABLAUF>.toml``) unter
``.local/handoff/steps/<BEAD>/record.json``: wartender Zustand und
Tatsachen für Wächter (z. B. kein PASS nach Teillauf). Daneben
steht ``events.jsonl``, dasselbe Ereignisprotokoll wie bei
``ki-dev -f implement``. Beads bleiben Auftrag und PM-Sicht; der
Laufzustand ist Arbeitsstand dieses Arbeitsbaums wie die
Vorlaufartefakte.

Ein ausdrückliches ``--step`` beginnt dort, ohne ``--step`` setzt step
den wartenden Zustand fort. Beginnt ein Aufruf woanders, als der letzte
endete, steht davor eine Zeile ``letzter Halt --@jump--> Start``, die
:func:`~ki_dev.runner.events.check_conformance` als Abweichung meldet.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ki_dev.flow.model import Flow, Transition
from ki_dev.flow.review_flow import load_review_flow
from ki_dev.run_store import RunStore
from ki_dev.runner.events import event_record
from ki_dev.runner.planning import Halt, read_waiting, recorded_flow

STATE_DIR = Path(".local") / "handoff" / "steps"
MANUAL = "manual"
JUMP = "@jump"
MACHINE = "ki-dev"

class StepStateError(ValueError):
    """Ort des Laufzustands ist für diese BEAD_ID ungültig."""


@dataclass(frozen=True)
class SavedState:
    flow: str
    state: str
    facts: frozenset[str]


def state_root() -> Path:
    return Path.cwd() / STATE_DIR


def step_dir(bead_id: str) -> Path:
    return _store(bead_id).run_dir


def load_state(bead_id: str) -> SavedState | None:
    """Wartender Ablauf und Zustand aus dem Datensatz oder ``None``."""
    directory = step_dir(bead_id)
    name = recorded_flow(directory)
    if name is None:
        return None
    waiting = read_waiting(load_review_flow(name).flow, directory)
    return None if waiting is None else SavedState(name, *waiting)


def remember(
    bead_id: str, halt: Halt, flow: Flow, previous: str | None
) -> None:
    """Genommene Kanten protokollieren, dann den Halt speichern.

    Beginnt der Aufruf woanders als ``previous`` (letzter Halt), steht
    davor eine Zeile ``previous --@jump--> start``: kein Übergang des
    Ablaufs, darum meldet check_conformance sie als Abweichung."""
    store = _store(bead_id)
    seq = len(store.load_events())
    start = halt.entry.source if halt.entry is not None else halt.state
    jumps = []
    if previous is not None and previous != start:
        jumps.append(
            Transition(source=previous, event=JUMP, target=start)
        )
    for transition in (*jumps, *halt.path):
        seq += 1
        store.append_event(
            event_record(
                line=seq,
                seq=seq,
                ts=datetime.now(UTC).isoformat(),
                flow=flow,
                run_id=bead_id,
                transition=transition,
                target=transition.target,
                adapter=_adapter(flow, transition.source),
            )
        )


def _adapter(flow: Flow, state: str) -> str:
    """Maschinenzustände erzeugen ihr Ereignis selbst; sonst trägt der
    Mensch die Antwort als Bote herein."""
    return MACHINE if flow.state(state).kind == "machine" else MANUAL


def _store(bead_id: str) -> RunStore:
    try:
        return RunStore(state_root(), bead_id)
    except ValueError as exc:
        raise StepStateError(f"BEAD_ID {bead_id!r}: {exc}") from exc
