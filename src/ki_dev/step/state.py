"""Laufzustand je Bead für ``ki-dev step`` (lokal, nicht in bd/Dolt).

Der Zustand ist der Datensatz des Ausführers
(:mod:`ki_dev.runner.package`) für den zuletzt gelaufenen Ablauf
unter ``.local/handoff/steps/<BEAD>/record.json``: Zustand des
Ablaufs, Halt des Laufs, wartender Versuch und Laufdaten für die
Wächter (z. B. kein PASS nach Teillauf). Daneben steht
``events.jsonl``, das Protokoll des Ausführers (Regionen). Beads
bleiben Auftrag und PM-Sicht; der Laufzustand ist Arbeitsstand
dieses Arbeitsbaums wie die Vorlaufartefakte.

Ein ausdrückliches ``--step`` beginnt dort, ohne ``--step`` setzt step
den wartenden Zustand fort. Beginnt ein Aufruf im selben Ablauf
woanders, als der letzte endete, protokolliert der Ausführer davor
``letzter Halt --@jump--> Start``, was
:func:`~ki_dev.runner.events.check_conformance` als Abweichung meldet.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ki_dev.flow.binding import BindingError
from ki_dev.flow.model import FlowError
from ki_dev.flow.review_flow import load_review_flow
from ki_dev.run_store import RunStore, RunStoreError
from ki_dev.runner.package import waiting_of

STATE_DIR = Path(".local") / "handoff" / "steps"


class StepStateError(ValueError):
    """Ort des Laufzustands ist für diese BEAD_ID ungültig."""


class StaleHaltError(FlowError):
    """Der gespeicherte Halt stammt aus einem anderen Ablaufstand."""


@dataclass(frozen=True)
class SavedState:
    flow: str
    state: str
    status: str
    """Halt des Laufs (z. B. ``awaiting_input``, ``finished``)."""
    attempt: str | None
    """Kennung des wartenden Versuchs (``None``: nichts wartet)."""


def state_root() -> Path:
    return Path.cwd() / STATE_DIR


def step_dir(bead_id: str) -> Path:
    return run_store(bead_id).run_dir


def run_store(bead_id: str) -> RunStore:
    """Ablage des Laufs dieses Beads (Datensatz, Protokoll)."""
    try:
        return RunStore(state_root(), bead_id)
    except ValueError as exc:
        raise StepStateError(f"BEAD_ID {bead_id!r}: {exc}") from exc


def load_state(bead_id: str) -> SavedState | None:
    """Ablauf, Zustand, Halt und Versuch aus dem Datensatz oder
    ``None`` ohne Lauf; ein Datensatz aus einem anderen Ablaufstand
    ist :class:`StaleHaltError`."""
    try:
        record = run_store(bead_id).load_record()
        if record is None:
            return None
        name = (
            record.get("flow") if isinstance(record, Mapping) else None
        )
        if not isinstance(name, str):
            raise RunStoreError("Datensatz ohne Ablauf")
        flow = load_review_flow(name).flow
        return SavedState(name, *waiting_of(flow, record))
    except (RunStoreError, BindingError, FlowError) as exc:
        raise StaleHaltError(
            "gespeicherter Halt stammt aus einem anderen "
            f"Ablaufstand; mit --step neu beginnen ({exc})"
        ) from exc

