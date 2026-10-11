"""Ereignisprotokoll je genommenem Übergang (JSONL, SCXML-Namen).

Jede Zeile ist eine genommene Kante einer Region:
``state --event [cond] / actions--> target``. ``region`` ist ``ablauf``
(der Ablauf des Pakets) oder eine Region des Laufs (``operation``,
``halt``, ``runner/run.toml``). ``line`` zählt alle Zeilen; eine
Wiederholung nach einem Absturz schreibt dieselbe Zeile nicht ein
zweites Mal. ``seq`` ist die Revision des Ablaufs: nach einer
Ablaufkante die neue, sonst die, in der die Kante stattfand.
:func:`check_conformance` gleicht ein Protokoll je Region gegen ihre
Definition ab: nützlich, wo ein Mensch abweichen kann; für
``ki-dev -f implement`` gilt es per Bauweise.

XES (IEEE 1849) wäre nur ein späterer Export; die Felder lassen sich
1:1 abbilden (``state`` → ``concept:name``, ``actor`` → ``org:role``,
``adapter`` → ``org:resource``, ``ts`` → ``time:timestamp``).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping

from jsonschema import Draft202012Validator

from ki_dev.flow.model import HISTORY, Flow, Transition, targets

EVENTS_FILE = "events.jsonl"

ABLAUF = "ablauf"
"""Region des Ablaufs; alle anderen gehören dem Lauf."""

RUN_FLOW = "run"
"""``flow`` der Zeilen einer Region des Laufs."""

MACHINE = "ki-dev"
"""Adapter eines Ereignisses, das ki-dev selbst erzeugt."""

_NAME = {"type": "string", "minLength": 1, "pattern": r"\S"}
_NAMES = {"type": "array", "items": _NAME}
EVENT_SCHEMA = {
    "type": "object",
    "required": [
        "line",
        "region",
        "seq",
        "ts",
        "flow",
        "run",
        "state",
        "event",
        "target",
        "cond",
        "actions",
        "escalation",
        "actor",
        "adapter",
    ],
    "additionalProperties": False,
    "properties": {
        "line": {"type": "integer", "minimum": 1},
        "region": _NAME,
        "seq": {"type": "integer", "minimum": 0},
        "ts": _NAME,
        "flow": _NAME,
        "run": _NAME,
        "state": _NAME,
        "event": _NAME,
        "target": _NAME,
        "cond": _NAMES,
        "actions": _NAMES,
        "escalation": {"anyOf": [{"type": "null"}, _NAME]},
        "actor": {"anyOf": [{"type": "null"}, _NAME]},
        "adapter": _NAME,
    },
}
_VALIDATOR = Draft202012Validator(EVENT_SCHEMA)


class EventLogError(ValueError):
    """Protokollzeile verletzt das Schema (Feldpfad, ohne Rohwerte)."""


def event_record(
    *,
    line: int,
    seq: int,
    ts: str,
    flow: Flow,
    run_id: str,
    transition: Transition,
    target: str,
    adapter: str,
) -> dict[str, object]:
    """Geprüfte Zeile für eine genommene Kante des Ablaufs; ``target``
    ist das tatsächliche Ziel (bei ``@history`` der
    Fortsetzungspunkt)."""
    record = {
        "line": line,
        "region": ABLAUF,
        "seq": seq,
        "ts": ts,
        "flow": flow.name,
        "run": run_id,
        "state": transition.source,
        "event": transition.event,
        "target": target,
        "cond": list(transition.cond),
        "actions": list(transition.actions),
        "escalation": transition.escalation,
        "actor": flow.state(transition.source).actor,
        "adapter": adapter,
    }
    validate_record(record)
    return record


def run_event_record(
    *,
    line: int,
    seq: int,
    ts: str,
    run_id: str,
    region: str,
    transition: Transition,
) -> dict[str, object]:
    """Geprüfte Zeile für eine genommene Kante einer Region des Laufs;
    ``state`` ist der Zustand, der die Kante deklariert."""
    record = {
        "line": line,
        "region": region,
        "seq": seq,
        "ts": ts,
        "flow": RUN_FLOW,
        "run": run_id,
        "state": transition.source,
        "event": transition.event,
        "target": transition.target,
        "cond": list(transition.cond),
        "actions": list(transition.actions),
        "escalation": None,
        "actor": None,
        "adapter": MACHINE,
    }
    validate_record(record)
    return record


def validate_record(record: object) -> None:
    errors = sorted(
        _VALIDATOR.iter_errors(record),
        key=lambda e: list(map(str, e.absolute_path)),
    )
    if errors:
        path = ".".join(map(str, errors[0].absolute_path)) or "$"
        raise EventLogError(f"{path}: {errors[0].validator}")


def check_conformance(
    flow: Flow,
    records: Iterable[dict[str, object]],
    run: Mapping | None = None,
) -> list[str]:
    """Abweichungen je Region von ihrer Definition; leer heißt konform.

    Zeilen der Region ``ablauf`` prüft :func:`_check_flow` gegen
    ``flow``, die der Regionen des Laufs :func:`_check_run` gegen
    ``run`` (``[statechart]`` von ``runner/run.toml``)."""
    lines = list(enumerate(records))
    problems = _check_flow(
        flow, [(i, r) for i, r in lines if r["region"] == ABLAUF]
    )
    regions = sorted({str(r["region"]) for _, r in lines} - {ABLAUF})
    for region in regions:
        rows = [(i, r) for i, r in lines if r["region"] == region]
        if run is None:
            problems.append(
                f"{rows[0][0]}: Region {region} ohne Definition"
            )
            continue
        problems += _check_run(run, region, rows)
    return sorted(problems, key=lambda p: int(p.split(":")[0]))


def _check_flow(
    flow: Flow, records: list[tuple[int, dict[str, object]]]
) -> list[str]:
    """Jede Zeile muss eine Kante (state, event) mit passendem Ziel
    sein, und jede Zeile beginnt dort, wo die vorige endete."""
    problems: list[str] = []
    previous: str | None = None
    for index, record in records:
        state, event = str(record["state"]), str(record["event"])
        target = str(record["target"])
        if previous is not None and state != previous:
            problems.append(
                f"{index}: beginnt in {state}, vorher endete {previous}"
            )
        if not any(
            _reaches(flow, t, target)
            for t in flow.candidates(state, event)
        ):
            problems.append(
                f"{index}: keine Kante {state} --{event}--> {target}"
            )
        previous = target
    return problems


def _check_run(
    run: Mapping,
    region: str,
    records: list[tuple[int, dict[str, object]]],
) -> list[str]:
    """Wie :func:`_check_flow`, aber ``state`` ist der Zustand, der die
    Kante deklariert: er ist der vorige Zielzustand oder einer seiner
    Vorfahren; ein Ereignis passt auch als Präfix (``escalation`` für
    ``escalation.agent``)."""
    (root,) = run["states"].values()
    states = root["states"].get(region)
    if states is None:
        return [f"{records[0][0]}: Region {region} unbekannt"]
    parents = dict(_parents({region: states}, None))
    edges = {
        (owner, item["event"], item.get("target", owner))
        for owner, state in _states({region: states})
        for item in state.get("transitions", ())
    }
    problems: list[str] = []
    previous: str | None = None
    for index, record in records:
        state, event = str(record["state"]), str(record["event"])
        target = str(record["target"])
        if previous is not None and state not in _chain(
            previous, parents
        ):
            problems.append(
                f"{index}: beginnt in {state}, vorher endete {previous}"
            )
        if not any(
            owner == state
            and to == target
            and (event == name or event.startswith(f"{name}."))
            for owner, name, to in edges
        ):
            problems.append(
                f"{index}: keine Kante {state} --{event}--> {target}"
            )
        previous = target
    return problems


def _states(states: Mapping) -> Iterator[tuple[str, Mapping]]:
    for sid, state in states.items():
        yield sid, state
        yield from _states(state.get("states", {}))


def _parents(
    states: Mapping, parent: str | None
) -> Iterator[tuple[str, str | None]]:
    for sid, state in states.items():
        yield sid, parent
        yield from _parents(state.get("states", {}), sid)


def _chain(state: str, parents: Mapping[str, str | None]) -> set[str]:
    chain: set[str] = set()
    current: str | None = state
    while current is not None:
        chain.add(current)
        current = parents.get(current)
    return chain


def _reaches(flow: Flow, transition: Transition, target: str) -> bool:
    if transition.target == HISTORY:
        return target in targets(flow, transition)
    return transition.target == target
