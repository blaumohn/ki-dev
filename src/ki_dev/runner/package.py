"""Der Ausführer: fährt einen Ablauf als Region der Lauf-Maschine.

Alle Regionen benutzen dieselbe Statechart-Bibliothek und run.toml.
Der Runner kennt Bindungen, JSON-Nutzdaten und Ereignisse, keine
Rollen und Phasen. Zwei Arten von Operationen:

- gebundene Katalogoperationen (``[op.*]``), ausgeführt über
  :class:`~ki_dev.runner.bound.BoundOperations`;
- Übergaben (``turn``, ``ask``: Operationen ohne Bindung), bearbeitet
  über die eingesteckte Übergabe (:data:`TurnRun`, etwa
  :class:`~ki_dev.runner.dispatch.Dispatch`). Fehlt die Antwort noch
  (:class:`~ki_dev.runner.protocol.AwaitingAnswer`), hält der Lauf in
  ``awaiting_input``; ``resume`` führt die Übergabe erneut aus.

Beide laufen im Zwei-Schreib-Protokoll der Region ``operation``:
Absicht speichern, Wirkung, Ergebnis speichern, dann das Ereignis.
Wächter und Aktionen des Ablaufs setzt das Modell des Pakets um (eine
Unterklasse von :class:`~ki_dev.runner.protocol.RunModel`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import cast

from ki_dev.flow.binding import OperationFailure, validate
from ki_dev.flow.model import Flow, Transition
from ki_dev.fsm import Durable, bind, configuration_of
from ki_dev.run_store import RunStore, RunStoreError
from ki_dev.runner.bound import BoundOperations
from ki_dev.runner.events import (
    LAUF,
    MACHINE,
    RESTART,
    event_record,
    run_event_record,
)
from ki_dev.runner.limits import (
    EMPTY_FLOW_SCHEMA,
    MEASUREMENT_SCHEMA,
    resolve,
)
from ki_dev.runner.protocol import (
    RUN_DOC,
    AwaitingAnswer,
    RunModel,
    compose,
)

JUMP = "@jump"
"""Ereignis der Protokollzeile eines Neubeginns an anderer Stelle."""


@dataclass(frozen=True)
class Handoff:
    """Eine Übergabe des Laufs: Zustand, Kennung des Versuchs (bindet
    die Antwort), die Laufdaten und der Weg dieses Aufrufs bis zu ihr
    (eine Kante kann die Übergabe bestimmen)."""

    state: str
    attempt: str
    data: Mapping[str, object]
    path: tuple[Transition, ...] = ()


TurnRun = Callable[[Handoff], Mapping[str, object]]
"""Bearbeitet eine Übergabe und liefert ``{"event": …, "update": …}``:
das Ereignis der Antwort und die neuen Laufdaten, dazu wahlweise
``"adapter"``: wer antwortete (Name des Executors, im Protokoll)."""


class PackageRunner:
    def __init__(
        self,
        flow: Flow,
        operations: BoundOperations,
        store: RunStore,
        *,
        max_steps: int = 1000,
        model: type[RunModel] = RunModel,
        turns: TurnRun | None = None,
        flow_limits: Mapping[str, object] | None = None,
        flow_limits_schema: Mapping[str, object] = EMPTY_FLOW_SCHEMA,
    ) -> None:
        """``flow_limits`` und ``flow_limits_schema``: Standardwerte
        und Schema der Ablaufgrenzen des Pakets (``limits.flow``)."""
        validate(
            max_steps, {"type": "integer", "minimum": 1}, "max_steps"
        )
        used = {
            op.do for s in flow.states.values() for op in s.operations
        }
        bound = used & set(flow.bindings)
        if bound != set(operations.bindings):
            raise RunStoreError(
                "Paket und Bindungen haben anderes Vokabular"
            )
        if dict(flow.bindings) != dict(operations.bindings):
            raise RunStoreError("Bindungen weichen vom Paket ab")
        if used - bound and turns is None:
            raise RunStoreError(
                "Übergaben ohne Bearbeiter: "
                + ", ".join(sorted(used - bound))
            )
        self.flow, self.operations, self.store = flow, operations, store
        self.turns = turns
        self.max_steps = max_steps
        self.model_type = model
        self.flow_limits = dict(flow_limits or {})
        self.flow_limits_schema = flow_limits_schema
        self.roles = {
            op.role
            for s in flow.states.values()
            for op in s.operations
            if op.role is not None
        }
        self.chart = bind(
            compose(RUN_DOC, flow.statechart),
            model,
            also=frozenset(
                g.removeprefix("!")
                for s in flow.states.values()
                for op in s.operations
                for g in op.cond
            )
            | set(flow.vocabulary.guards)
            | set(flow.vocabulary.actions),
        )
        self.regions = {}
        self.items = {}
        for region, state in self.chart.doc["states"]["lauf"][
            "states"
        ].items():
            for sid, item in _walk({region: state}):
                self.regions[sid] = region
                for index, transition in enumerate(
                    item.get("transitions", ())
                ):
                    self.items[(sid, index)] = transition
        self.digest = flow_digest(flow)
        self.path: list[Transition] = []

    def start(
        self,
        data: dict,
        at: str | None = None,
        *,
        again: bool = False,
        limits: Mapping[str, object] | None = None,
    ) -> dict:
        """Neuer Lauf am Start des Ablaufs oder in ``at``. Ein
        gespeicherter Lauf bleibt, außer ``again`` beginnt ausdrücklich
        neu (Zähler für Protokoll und Versuche laufen weiter).
        ``limits``: Grenzwerte dieses Laufs; was fehlt, ist
        Standardwert (:func:`~ki_dev.runner.limits.resolve`)."""
        limits = resolve(
            limits or {},
            self.roles,
            self.flow_limits,
            self.flow_limits_schema,
        )
        with self.store.acquire_writer():
            previous = self.store.load_record()
            if previous is not None and not again:
                raise RunStoreError(
                    f"Lauf {self.store.run_id} existiert bereits unter "
                    f"{self.store.root}; status und resume zeigen und "
                    "setzen ihn fort, eine andere Lauf-ID beginnt neu"
                )
            self.path = []
            self.data = dict(data)
            self.model = self.model_type(data=self.data, limits=limits)
            self.machine = Durable(
                self.chart,
                self.model,
                None if at is None else self._at(at),
            )
            self.revision = 0
            self.line = 0
            self.attempts = 0
            if previous is None:
                self.store.initialize(
                    {"package": self.flow.name, "digest": self.digest}
                )
            else:
                self.line = int(previous.get("line", 0))
                self.attempts = int(previous.get("attempts", 0))
                self._restart()
                self._jump(previous)
            self._save()
            return self._drive()

    def resume(self) -> dict:
        with self.store.acquire_writer():
            self._load()
            self.path = []
            if self.status in {"running", "awaiting_input", "stopped"}:
                self._send("resume")
                self._save()
            return self._drive()

    def reconcile(self, artifact: object) -> dict:
        with self.store.acquire_writer():
            self._load()
            self.path = []
            if self.status != "uncertain" or self.model.pending is None:
                raise RunStoreError(
                    "Lauf wartet nicht auf einen Abgleich"
                )
            pending = self.model.pending
            self._accept(pending, artifact)
            self.store.write_artifact(
                pending["id"], {"result": artifact}
            )
            self._send("reconcile")
            self._save()
            return self._drive()

    def _restart(self) -> None:
        """Ein neuer Lauf im selben Protokoll: die Regionen des Laufs
        beginnen wieder im Anfangszustand (Zeile
        ``lauf --@start--> lauf``)."""
        self.line += 1
        self.store.append_event(
            run_event_record(
                line=self.line,
                seq=self.revision,
                ts=datetime.now(UTC).isoformat(),
                run_id=self.store.run_id,
                region=LAUF,
                transition=Transition(LAUF, RESTART, LAUF),
            )
        )

    def _jump(self, previous: Mapping[str, object]) -> None:
        """Beginnt ein neuer Lauf desselben Ablaufs woanders, als der
        letzte hielt, steht ``letzter Halt --@jump--> Start`` im
        Protokoll; ``check_conformance`` meldet es als Abweichung."""
        if (
            previous.get("flow") != self.flow.name
            or "machine" not in previous
        ):
            return
        machine = cast(Mapping[str, list[str]], previous["machine"])
        last = next(
            (s for s in machine["state"] if s in self.flow.states),
            None,
        )
        if last is None or last == self.state:
            return
        self.line += 1
        self.store.append_event(
            event_record(
                line=self.line,
                seq=self.revision,
                ts=datetime.now(UTC).isoformat(),
                flow=self.flow,
                run_id=self.store.run_id,
                transition=Transition(last, JUMP, self.state),
                target=self.state,
                adapter=MACHINE,
            )
        )

    @property
    def status(self) -> str:
        states = RUN_DOC["states"]["lauf"]["states"]["halt"]["states"]
        return next(
            s for s in self.machine.configuration if s in states
        )

    @property
    def state(self) -> str:
        return next(
            s
            for s in self.machine.configuration
            if s in self.flow.states
        )

    def _at(self, state: str) -> dict:
        """Datensatz einer frischen Maschine, deren Ablauf in
        ``state`` steht (Start an einem Zustand)."""
        self.flow.state(state)
        fresh = Durable(self.chart, self.model_type())
        rest = [
            s
            for s in fresh.configuration
            if self.regions.get(s) != "ablauf"
        ]
        chain = configuration_of(self.chart, state)
        ablauf = chain[chain.index("ablauf") :]
        configuration = []
        for item in (*rest[:1], *ablauf, *rest[1:]):
            if item not in configuration:
                configuration.append(item)
        return {"state": configuration, "history": {}}

    def _drive(self) -> dict:
        while self.status == "running":
            if self.revision >= self.max_steps:
                raise RunStoreError("Technische Schrittgrenze erreicht")
            self._step()
            self._save()
        pending = self.model.pending
        return {
            "status": self.status,
            "state": self.state,
            "data": self.data,
            "path": list(self.path),
            "attempt": None if pending is None else pending["attempt"],
            "reason": self.model.halt_reason,
        }

    def _holds(self, name: str) -> bool:
        return bool(getattr(self.model, name)())

    def _step(self) -> None:
        operation = self.flow.operation(self.state, self._holds)
        if operation is None:
            raise RunStoreError("Aktiver Zustand hat keine Operation")
        if self.model.pending is None:
            attempt = None
            if operation.do in self.operations.bindings:
                self.operations.inputs(operation.do, self.data)
            else:
                self.attempts += 1
                attempt = f"{self.store.run_id}:{self.attempts}"
            self._send(
                "hold",
                operation={
                    # Protokollzeile des Halts: sie läuft auch über
                    # einen Neubeginn (again) weiter, eine Kennung
                    # trifft also nie ein Artefakt eines alten Laufs.
                    "id": f"op-{self.line + 1:08d}",
                    "kind": operation.do,
                    "repeatable": operation.repeatable,
                    "attempt": attempt,
                },
            )
            return
        pending = dict(self.model.pending)
        if pending["kind"] != operation.do:
            raise RunStoreError(
                "Offene Operation passt nicht zum Zustand"
            )
        artifact = self.store.load_artifact(pending["id"])
        if artifact is None:
            if "started" in self.machine.configuration:
                self._send("interrupted")
                if self.status != "running":
                    return
            else:
                self._send("start")
                self._save()
            try:
                artifact = self._execute(pending)
            except AwaitingAnswer:
                self._send("answer_pending")
                return
            except OperationFailure:
                if operation.failure is None:
                    raise
                # Auch ein Fehlerergebnis ist ein dauerhafter Nachweis.
                artifact = {"failure": operation.failure}
                self.store.write_artifact(
                    pending["id"], {"failed": artifact}
                )
                self._failure(operation.failure)
                return
            self.store.write_artifact(
                pending["id"], {"result": artifact}
            )
        else:
            validate(artifact, _ARTIFACT, "artifact")
            if "failed" in artifact:
                if artifact["failed"]["failure"] != operation.failure:
                    raise RunStoreError(
                        "Fehlerereignis passt nicht zum Paket"
                    )
                self._failure(operation.failure)
                return
            artifact = artifact["result"]
        update, event = self._accept(pending, artifact)
        self._send("artifact_saved")
        self.data.update(update)
        by = (
            MACHINE
            if pending["kind"] in self.operations.bindings
            else _answered_by(artifact)
        )
        self._send(event, by=by, payload=artifact)

    def _execute(self, pending: Mapping[str, object]) -> object:
        kind = str(pending["kind"])
        if kind in self.operations.bindings:
            return self.operations.execute(kind, self.data)
        assert self.turns is not None
        handoff = Handoff(
            self.state,
            str(pending["attempt"]),
            dict(self.data),
            tuple(self.path),
        )
        return dict(self.turns(handoff))

    def _accept(
        self, pending: Mapping[str, object], artifact: object
    ) -> tuple[dict, str]:
        kind = str(pending["kind"])
        if kind in self.operations.bindings:
            return self.operations.accept(kind, artifact)
        validate(artifact, _ANSWER, f"{kind}.answer")
        answer = dict(artifact)  # type: ignore[call-overload]
        return dict(answer["update"]), str(answer["event"])

    def _failure(self, event: str) -> None:
        self._send("failed")
        self._send(event)

    def _send(
        self, event: str, by: str = MACHINE, **kwargs: object
    ) -> None:
        """Ereignis an die Lauf-Maschine; jede genommene Kante wird
        protokolliert, die des Ablaufs mit ``by`` (wer das Ereignis
        brachte)."""
        source = self.state
        if event == "measured":
            validate(
                kwargs.get("measurement"), MEASUREMENT_SCHEMA, event
            )
        self.machine.send(event, **kwargs)
        if self.status == "running":
            self.model.halt_reason = None
        for taken in self.machine.journal:
            region = self.regions[taken.owner]
            key = (taken.owner, taken.index, source)
            if region == "ablauf" and key not in self.flow.edges:
                continue  # raise-Empfänger ohne eigene Ablaufkante
            self.line += 1
            common = {
                "line": self.line,
                "ts": datetime.now(UTC).isoformat(),
                "run_id": self.store.run_id,
            }
            if region == "ablauf":
                self.revision += 1
                self.path.append(self.flow.edges[key])
                row = event_record(
                    **common,
                    seq=self.revision,
                    flow=self.flow,
                    transition=self.flow.edges[key],
                    target=self.state,
                    adapter=by,
                )
            else:
                item = self.items[(taken.owner, taken.index)]
                row = run_event_record(
                    **common,
                    seq=self.revision,
                    region=region,
                    transition=Transition(
                        taken.owner,
                        taken.event,
                        taken.target,
                        cond=(
                            *_names(item.get("cond")),
                            *(
                                "!" + n
                                for n in _names(item.get("unless"))
                            ),
                        ),
                        actions=tuple(_names(item.get("on"))),
                    ),
                )
            self.store.append_event(row)
        self.machine.journal.clear()

    def _save(self) -> None:
        self.store.save_record(
            {
                "flow": self.flow.name,
                "digest": self.digest,
                "machine": self.machine.record,
                "pending": self.model.pending,
                "data": self.data,
                "limits": self.model.limits,
                "halt_reason": self.model.halt_reason,
                "revision": self.revision,
                "line": self.line,
                "attempts": self.attempts,
                "max_steps": self.max_steps,
            }
        )

    def _load(self) -> None:
        record = self.store.load_record()
        validate(record, _RECORD, "record")
        if record["digest"] != self.digest:
            raise RunStoreError("Paket wurde seit Laufbeginn verändert")
        self.data = record["data"]
        self.model = self.model_type(
            record["pending"], self.data, record["limits"]
        )
        self.model.halt_reason = record["halt_reason"]
        self.machine = Durable(
            self.chart, self.model, record["machine"]
        )
        self.revision = record["revision"]
        self.line = record["line"]
        self.attempts = record["attempts"]
        self.max_steps = record["max_steps"]


def _answered_by(answer: object) -> str:
    """Wer eine Übergabe beantwortete (geprüfte Antwort): der
    Executor, sonst ki-dev selbst."""
    by = answer.get("adapter") if isinstance(answer, Mapping) else None
    return by if isinstance(by, str) else MACHINE


def flow_digest(flow: Flow) -> str:
    """Fingerabdruck von Ablauf und Lauf-Maschine: ändert er sich,
    passt ein gespeicherter Lauf nicht mehr."""
    document = asdict(flow)
    document.pop("edges")
    # Der Ort des Pakets gehört nicht zum Ablauf (verschiebbar).
    document.pop("root")
    encoded = json.dumps([document, RUN_DOC], sort_keys=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


_ANSWER = {
    "type": "object",
    "required": ["event", "update"],
    "additionalProperties": False,
    "properties": {
        "event": {"type": "string", "minLength": 1},
        "update": {"type": "object"},
        "adapter": {"type": "string", "minLength": 1},
    },
}
_ARTIFACT = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "result": {},
        "failed": {
            "type": "object",
            "required": ["failure"],
            "additionalProperties": False,
            "properties": {"failure": {"type": "string"}},
        },
    },
    "oneOf": [{"required": ["result"]}, {"required": ["failed"]}],
}
_RECORD = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "flow",
        "digest",
        "machine",
        "pending",
        "data",
        "limits",
        "halt_reason",
        "revision",
        "line",
        "attempts",
        "max_steps",
    ],
    "properties": {
        "flow": {"type": "string"},
        "digest": {"type": "string"},
        "machine": {"type": "object"},
        "data": {"type": "object"},
        "limits": {"type": "object"},
        "halt_reason": {
            "anyOf": [{"type": "null"}, {"type": "string"}]
        },
        "pending": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "id",
                        "kind",
                        "repeatable",
                        "attempt",
                        "call_id",
                    ],
                    "properties": {
                        "id": {
                            "type": "string",
                            "pattern": r"^op-[0-9]{8,}$",
                        },
                        "kind": {"type": "string"},
                        "repeatable": {"type": "boolean"},
                        "attempt": {
                            "anyOf": [
                                {"type": "null"},
                                {"type": "string"},
                            ]
                        },
                        "call_id": {"type": "null"},
                    },
                },
            ]
        },
        "revision": {"type": "integer", "minimum": 0},
        "line": {"type": "integer", "minimum": 0},
        "attempts": {"type": "integer", "minimum": 0},
        "max_steps": {"type": "integer", "minimum": 1},
    },
}


def _walk(states):
    for sid, item in states.items():
        yield sid, item
        yield from _walk(item.get("states", {}))


def _names(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
