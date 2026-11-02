"""Gemeinsame technische Regionen; kennen keine Paketrollen."""

from __future__ import annotations

import copy
import tomllib
from collections.abc import Mapping
from importlib.resources import files

from ki_dev.runner.limits import limit_reasons

Operation = dict[str, object]
_ROOT = "lauf"
ABLAUF = "ablauf"


class AwaitingAnswer(Exception):
    """Die Übergabe ist ausgegeben, die Antwort fehlt noch (Bote): der
    Lauf hält in ``awaiting_input``; ``resume`` führt die Übergabe
    erneut aus."""


class TurnFailed(Exception):
    """Der Executor ist gescheitert, der Verbrauch ist verbucht: der
    Lauf hält in ``stopped`` mit dieser Ursache (kein Traceback)."""


class RunModel:
    """Ops der Regionen ``operation`` und ``halt``: die offene
    Operation. Ein Paket erweitert sie um die Wächter und Aktionen
    seines Ablaufs; sie lesen die Laufdaten (``data``) und die
    Grenzwerte des Laufs (``limits``, :mod:`ki_dev.runner.limits`)."""

    def __init__(
        self,
        pending: Operation | None = None,
        data: dict[str, object] | None = None,
        limits: Mapping[str, object] | None = None,
    ) -> None:
        self.pending = pending
        self.data = {} if data is None else data
        self.limits = {} if limits is None else dict(limits)
        self.halt_reason: str | None = None

    def is_running(self, machine: object) -> bool:
        """Region halt fährt (kein Halt)."""
        return machine.running.is_active  # type: ignore[attr-defined]

    def repeatable(self) -> bool:
        """Die offene Operation darf nach Prozessende erneut laufen."""
        return self.pending is not None and bool(
            self.pending["repeatable"]
        )

    def within_limits(self, measurement: Mapping) -> bool:
        """Die Messung liegt unter allen Grenzwerten des Laufs."""
        return not limit_reasons(measurement, self.limits)

    def note_stop(self, measurement: Mapping) -> None:
        """Alle erreichten Grenzen als Grund des Schutzhalts ablegen."""
        self.halt_reason = "; ".join(
            limit_reasons(measurement, self.limits)
        )

    def hold_operation(self, operation: Operation) -> None:
        self.pending = {**operation, "call_id": None}

    def begin_operation(self, call_id: str | None = None) -> None:
        """Absicht: die Wirkung beginnt (mit Budgetbuchung)."""
        self.pending = {**self.pending, "call_id": call_id}

    def note_failure(self, reason: str) -> None:
        """Ursache eines gescheiterten Executors als Grund des Halts."""
        self.halt_reason = reason

    def drop_operation(self) -> None:
        self.pending = None


def compose(run: Mapping, flow: Mapping) -> dict:
    """Lauf mit dem Ablauf als Region :data:`ABLAUF`."""
    doc = copy.deepcopy(dict(run))
    root = doc["states"][_ROOT]
    root["states"] = {
        ABLAUF: {"states": copy.deepcopy(flow["states"])},
        **root["states"],
    }
    return doc


def _load_doc() -> dict:
    text = (
        files("ki_dev.runner")
        .joinpath("run.toml")
        .read_text(encoding="utf-8")
    )
    return tomllib.loads(text)["statechart"]


RUN_DOC = _load_doc()
