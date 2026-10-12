"""Dauerhafte Ausführung reiner Datenpakete mit injiziertem Katalog.

Alle Regionen benutzen dieselbe Statechart-Bibliothek und run.toml.
Der Runner kennt Bindungen, JSON-Nutzdaten und Ereignisse.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime

from ki_dev.flow.binding import OperationFailure, validate
from ki_dev.flow.model import Flow, Transition
from ki_dev.fsm import Durable, bind
from ki_dev.run_store import RunStore, RunStoreError
from ki_dev.runner.bound import BoundOperations
from ki_dev.runner.events import event_record, run_event_record
from ki_dev.runner.protocol import RUN_DOC, RunModel, compose


class PackageRunner:
    def __init__(
        self,
        flow: Flow,
        operations: BoundOperations,
        store: RunStore,
        *,
        max_steps: int = 1000,
    ) -> None:
        validate(
            max_steps, {"type": "integer", "minimum": 1}, "max_steps"
        )
        used = {
            op.do for s in flow.states.values() for op in s.operations
        }
        if used != set(operations.bindings):
            raise RunStoreError(
                "Paket und Bindungen haben anderes Vokabular"
            )
        if dict(flow.bindings) != dict(operations.bindings):
            raise RunStoreError("Bindungen weichen vom Paket ab")
        self.flow, self.operations, self.store = flow, operations, store
        self.max_steps = max_steps
        self.chart = bind(
            compose(RUN_DOC, flow.statechart),
            RunModel,
            also=frozenset(
                g.removeprefix("!")
                for s in flow.states.values()
                for op in s.operations
                for g in op.cond
            ),
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
        document = asdict(flow)
        document.pop("edges")
        encoded = json.dumps([document, RUN_DOC], sort_keys=True)
        self.digest = hashlib.sha256(encoded.encode()).hexdigest()

    def start(self, data: dict) -> dict:
        with self.store.acquire_writer():
            if self.store.load_record() is not None:
                raise RunStoreError("Lauf existiert bereits")
            self.model = RunModel()
            self.machine = Durable(self.chart, self.model)
            self.data = dict(data)
            self.revision = 0
            self.line = 0
            self.store.initialize(
                {"package": self.flow.name, "digest": self.digest}
            )
            self._save()
            return self._drive()

    def resume(self) -> dict:
        with self.store.acquire_writer():
            self._load()
            if self.status in {"running", "awaiting_input"}:
                self._send("resume")
                self._save()
            return self._drive()

    def reconcile(self, artifact: object) -> dict:
        with self.store.acquire_writer():
            self._load()
            if self.status != "uncertain" or self.model.pending is None:
                raise RunStoreError(
                    "Lauf wartet nicht auf einen Abgleich"
                )
            pending = self.model.pending
            self.operations.accept(pending["kind"], artifact)
            self.store.write_artifact(
                pending["id"], {"result": artifact}
            )
            self._send("reconcile")
            self._save()
            return self._drive()

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

    def _drive(self) -> dict:
        while self.status == "running":
            if self.revision >= self.max_steps:
                raise RunStoreError("Technische Schrittgrenze erreicht")
            self._step()
            self._save()
        return {
            "status": self.status,
            "state": self.state,
            "data": self.data,
        }

    def _step(self) -> None:
        operation = self.flow.operation(self.state, lambda _: False)
        if operation is None:
            raise RunStoreError("Aktiver Zustand hat keine Operation")
        if self.model.pending is None:
            self.operations.inputs(operation.do, self.data)
            self._send(
                "hold",
                operation={
                    "id": f"op-{self.revision:08d}",
                    "kind": operation.do,
                    "repeatable": operation.repeatable,
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
                artifact = self.operations.execute(
                    pending["kind"], self.data
                )
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
        update, event = self.operations.accept(
            pending["kind"], artifact
        )
        self._send("artifact_saved")
        self.data.update(update)
        self._send(event, payload=artifact)

    def _failure(self, event: str) -> None:
        self._send("failed")
        self._send(event)

    def _send(self, event: str, **kwargs: object) -> None:
        source = self.state
        self.machine.send(event, **kwargs)
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
                row = event_record(
                    **common,
                    seq=self.revision,
                    flow=self.flow,
                    transition=self.flow.edges[key],
                    target=self.state,
                    adapter="ki-dev",
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
                "digest": self.digest,
                "machine": self.machine.record,
                "pending": self.model.pending,
                "data": self.data,
                "revision": self.revision,
                "line": self.line,
                "max_steps": self.max_steps,
            }
        )

    def _load(self) -> None:
        record = self.store.load_record()
        validate(record, _RECORD, "record")
        if record["digest"] != self.digest:
            raise RunStoreError("Paket wurde seit Laufbeginn verändert")
        self.model = RunModel(record["pending"])
        self.machine = Durable(
            self.chart, self.model, record["machine"]
        )
        self.data, self.revision = record["data"], record["revision"]
        self.line = record["line"]
        self.max_steps = record["max_steps"]


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
        "digest",
        "machine",
        "pending",
        "data",
        "revision",
        "line",
        "max_steps",
    ],
    "properties": {
        "digest": {"type": "string"},
        "machine": {"type": "object"},
        "data": {"type": "object"},
        "pending": {
            "anyOf": [
                {"type": "null"},
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "kind", "repeatable", "call_id"],
                    "properties": {
                        "id": {
                            "type": "string",
                            "pattern": r"^op-[0-9]{8,}$",
                        },
                        "kind": {"type": "string"},
                        "repeatable": {"type": "boolean"},
                        "call_id": {"type": "null"},
                    },
                },
            ]
        },
        "revision": {"type": "integer", "minimum": 0},
        "line": {"type": "integer", "minimum": 0},
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
