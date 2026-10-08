"""Laufzustand je Bead für ``ki-dev step`` (lokal, nicht in bd/Dolt).

Jeder Aufruf endet in einem Halt des Planungsablaufs; dieser Halt und
die genommenen Kanten bleiben unter ``.local/handoff/steps/<BEAD>/``:
``state.json`` (Zustand und Tatsachen für Wächter, z. B. kein PASS nach
Teillauf) und ``events.jsonl`` (dasselbe Ereignisprotokoll wie bei
``ki-dev run``). Beads bleiben Auftrag und PM-Sicht; der Laufzustand
ist Arbeitsstand dieses Arbeitsbaums wie die Vorlaufartefakte.

Ein ausdrückliches ``--step`` beginnt dort, ohne ``--step`` setzt step
den gespeicherten Zustand fort. Beginnt ein Aufruf woanders, als der
letzte endete, zeigt :func:`~ki_dev.runner.events.check_conformance`
die Abweichung im Protokoll.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jsonschema import Draft202012Validator

from ki_dev.flow.model import Flow
from ki_dev.run_store import RunStore
from ki_dev.runner.events import event_record
from ki_dev.runner.planning import Halt, PlanningContext

STATE_DIR = Path(".local") / "handoff" / "steps"
STATE_FILE = "state.json"
MANUAL = "manual"
MACHINE = "ki-dev"

_NAME = {"type": "string", "pattern": r"^[a-z_.]+$"}
_VALIDATOR = Draft202012Validator(
    {
        "type": "object",
        "required": ["state", "facts"],
        "additionalProperties": False,
        "properties": {
            "state": _NAME,
            "facts": {
                "type": "array",
                "uniqueItems": True,
                "items": _NAME,
            },
        },
    }
)


class StepStateError(ValueError):
    """Gespeicherter Zustand ist unlesbar oder verletzt sein Schema."""


@dataclass(frozen=True)
class SavedState:
    state: str
    facts: frozenset[str]

    def context(self) -> PlanningContext:
        return PlanningContext(facts=self.facts)


def state_root() -> Path:
    return Path.cwd() / STATE_DIR


def load_state(bead_id: str) -> SavedState | None:
    path = _store(bead_id).run_dir / STATE_FILE
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StepStateError(f"{path}: nicht lesbar") from exc
    errors = list(_VALIDATOR.iter_errors(value))
    if errors:
        field = ".".join(map(str, errors[0].absolute_path)) or "$"
        raise StepStateError(f"{path}: {field}: {errors[0].validator}")
    return SavedState(value["state"], frozenset(value["facts"]))


def remember(bead_id: str, halt: Halt, flow: Flow) -> None:
    """Genommene Kanten protokollieren, dann den Halt speichern."""
    store = _store(bead_id)
    seq = len(store.load_events())
    for transition in halt.path:
        seq += 1
        store.append_event(
            event_record(
                seq=seq,
                ts=datetime.now(UTC).isoformat(),
                flow=flow,
                run_id=bead_id,
                transition=transition,
                target=transition.target,
                adapter=_adapter(flow, transition.source),
            )
        )
    _replace_json(
        store.run_dir / STATE_FILE,
        {"state": halt.state, "facts": sorted(halt.context.facts)},
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


def _replace_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
