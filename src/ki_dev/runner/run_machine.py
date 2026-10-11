"""Lauf-Maschine des Ausführers: Status und offene Operation.

Die Topologie steht in ``runner/run.toml`` (natives Format von
python-statemachine); :class:`RunModel` liefert die Namen, die sie
nennt. :class:`RunMachine` ist die Sicht des Ausführers: Ereignis
senden, Status lesen, Datensatz bilden. Die Operation ist in
``running`` verschachtelt (eine Statechart statt zweier gekoppelter
Maschinen): ihre Halte (``awaiting_input``, ``uncertain``) sind
Zustände des Laufs, ohne Kopplungscode im Ausführer.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from importlib.resources import files

from ki_dev.fsm import Durable, bind

Operation = dict[str, object]
"""Offene Operation: ``id``, ``kind``, ``repeatable``, ``call_id``."""


class RunModel:
    """Ops der Lauf-Maschine: die offene Operation."""

    def __init__(self, pending: Operation | None = None) -> None:
        self.pending = pending

    def repeatable(self) -> bool:
        """Die offene Operation darf nach Prozessende erneut laufen."""
        return self.pending is not None and bool(
            self.pending["repeatable"]
        )

    def hold_operation(self, operation: Operation) -> None:
        self.pending = {**operation, "call_id": None}

    def begin_operation(self, call_id: str | None = None) -> None:
        """Absicht: die Wirkung beginnt (mit Budgetbuchung)."""
        self.pending = {**self.pending, "call_id": call_id}

    def drop_operation(self) -> None:
        self.pending = None


def _load_doc() -> dict:
    text = files("ki_dev.runner").joinpath("run.toml").read_text(
        encoding="utf-8"
    )
    return tomllib.loads(text)["statechart"]


RUN_CHART = bind(_load_doc(), RunModel)
_RUNNING = next(
    sid
    for sid, state in RUN_CHART.doc["states"].items()
    if state.get("initial")
)


class RunMachine:
    """Lauf-Maschine eines Laufs, wiederhergestellt aus Datensatz und
    offener Operation."""

    def __init__(
        self,
        record: Mapping[str, object] | None = None,
        pending: Operation | None = None,
    ) -> None:
        self._model = RunModel(pending)
        self._machine = Durable(RUN_CHART, self._model, record)

    def send(self, event: str, **kwargs: object) -> None:
        self._machine.send(event, **kwargs)

    @property
    def status(self) -> str:
        """Status des Laufs: der äußere Zustand."""
        return self._machine.configuration[0]

    @property
    def halted(self) -> bool:
        """Der Aufruf endet: der Lauf fährt nicht."""
        return self.status != _RUNNING

    @property
    def allowed(self) -> list[str]:
        """Ereignisse, die im aktuellen Status eine Kante haben."""
        events = self._machine.machine.allowed_events
        return sorted({str(event) for event in events})

    @property
    def started(self) -> bool:
        """Absicht gespeichert, Ergebnis noch nicht."""
        return self._machine.machine.started.is_active

    @property
    def pending(self) -> Operation | None:
        return self._model.pending

    @property
    def record(self) -> dict[str, object]:
        return self._machine.record
