"""Strenge Pruefung des JSON-Vertrags des Laufzustands.

Geprueft werden drei Dinge getrennt: dass der Roundtrip
``decode_run_state(encode_run_state(run))`` jeden Wert des gesamten
akzeptierten Zustandsraums erhaelt, dass jede Formabweichung eines
Dokuments sichtbar mit :class:`RunStateFormatError` abgewiesen wird und
dass eine fachliche Verletzung im sonst formgueltigen Dokument nicht
verdeckt, sondern von ``contract`` abgewiesen wird.

Fachliche Regeln (nicht leerer Text, Mindestgrenzen, nicht negative
Zaehler) bleiben Sache von ``contract``; hier wird nur belegt, dass die
Serialisierungsschicht sie nicht verdeckt.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ki_dev.ausfuehrer.machine import (
    SCHEMA_VERSION,
    AgentEscalation,
    Counters,
    Limits,
    MachineEscalation,
    MachineEscalationCause,
    MachineState,
    Phase,
    RunState,
    RunStateFormatError,
    decode_run_state,
    encode_run_state,
)

_FULL_STATE = MachineState(
    phase=Phase.CHECKPOINT,
    counters=Counters(
        protocol_attempt=1,
        worker_attempt=2,
        process_retry=3,
        changes_round=4,
    ),
    checkpointed_result=True,
)

_AGENT = AgentEscalation("Werkzeug unklar", Phase.WORKER_STEP)
_MACHINE = MachineEscalation(
    cause=MachineEscalationCause.WORKER_ATTEMPTS_EXHAUSTED,
    resume_point=Phase.CONTROLLER_STEP,
)


def _run(**overrides: object) -> RunState:
    fields: dict[str, object] = {
        "run_id": "run-1",
        "revision": 5,
        "state": _FULL_STATE,
        "limits": Limits(
            protocol_attempts=4,
            worker_attempts=9,
            changes_rounds=6,
            process_retries=2,
        ),
    }
    fields.update(overrides)
    return RunState(**fields)


def _document(**overrides: object) -> dict[str, object]:
    """Frisches, garantiert gueltiges Dokument je Aufruf."""
    return encode_run_state(_run(**overrides))


# -- Roundtrip -------------------------------------------------------


@pytest.mark.parametrize(
    "escalation",
    [None, _AGENT, _MACHINE],
    ids=["none", "agent", "machine"],
)
def test_roundtrip_keeps_the_run(escalation: object):
    run = _run(escalation=escalation)
    assert decode_run_state(encode_run_state(run)) == run


@pytest.mark.parametrize("phase", list(Phase))
def test_roundtrip_keeps_every_phase(phase: Phase):
    run = _run(state=MachineState(phase=phase))
    assert decode_run_state(encode_run_state(run)).state.phase is phase


def test_roundtrip_keeps_limits_and_counters():
    restored = decode_run_state(encode_run_state(_run()))
    assert restored.limits == _run().limits
    assert restored.state.counters == _FULL_STATE.counters
    assert restored.state.checkpointed_result is True


def test_run_total_is_derived_not_stored():
    document = _document()
    assert "run_total" not in document["state"]["counters"]
    restored = decode_run_state(document)
    assert restored.state.counters.run_total == 6


def test_document_survives_json_dumps():
    run = _run(escalation=_MACHINE)
    wire = json.dumps(encode_run_state(run))
    assert decode_run_state(json.loads(wire)) == run


def test_encoded_schema_version_is_pinned():
    assert _document()["schema_version"] == SCHEMA_VERSION


# -- Durchgriff fachlicher Regeln ---------------------------------


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d.update(revision=-1), "darf nicht negativ sein"),
        (lambda d: d.update(run_id=""), "darf nicht leer sein"),
        (
            lambda d: d["limits"].update(worker_attempts=0),
            "mindestens 1",
        ),
        (
            lambda d: d["state"]["counters"].update(worker_attempt=-1),
            "nicht negativ",
        ),
    ],
)
def test_business_rules_are_not_swallowed(mutate, match: str):
    """Formal gueltig, fachlich ungueltig: contract weist ab."""
    document = _document()
    mutate(document)
    with pytest.raises(ValueError, match=match):
        decode_run_state(document)


# -- Ganzes Dokument ------------------------------------------------


@pytest.mark.parametrize("value", [None, [], "x", 3, True])
def test_non_object_document_is_rejected(value: object):
    with pytest.raises(
        RunStateFormatError, match="JSON-Objekt erwartet"
    ):
        decode_run_state(value)


@pytest.mark.parametrize("version", [0, 2, -1, 99])
def test_unknown_schema_version_is_rejected(version: int):
    with pytest.raises(RunStateFormatError, match="nicht unterstuetzt"):
        decode_run_state(_document() | {"schema_version": version})


# -- Fehlende, zusaetzliche, falsch getippte Felder ----------------

_DROP: list[tuple[Callable[[dict], object], str]] = [
    (lambda d: d.pop("revision"), "run_state"),
    (lambda d: d["limits"].pop("worker_attempts"), "limits"),
    (lambda d: d["state"].pop("phase"), "state"),
    (
        lambda d: d["state"]["counters"].pop("worker_attempt"),
        "counters",
    ),
    (lambda d: _agent_doc(d)["escalation"].pop("cause"), "escalation"),
]

_ADD: list[tuple[Callable[[dict], object], str]] = [
    (lambda d: d.update(extra=1), "run_state"),
    (lambda d: d["limits"].update(extra=1), "limits"),
    (lambda d: d["state"].update(extra=1), "state"),
    (lambda d: d["state"]["counters"].update(extra=1), "counters"),
    (
        lambda d: _agent_doc(d)["escalation"].update(extra=1),
        "escalation",
    ),
]


def _agent_doc(document: dict[str, object]) -> dict[str, object]:
    """Setze eine Agenteneskalation und gib das Dokument zurueck."""
    document["escalation"] = encode_run_state(_run(escalation=_AGENT))[
        "escalation"
    ]
    return document


@pytest.mark.parametrize(
    ("mutate", "path"), _DROP, ids=[path for _, path in _DROP]
)
def test_missing_field_is_rejected(mutate, path: str):
    document = _document()
    mutate(document)
    with pytest.raises(RunStateFormatError, match="fehlende Felder"):
        decode_run_state(document)


@pytest.mark.parametrize(
    ("mutate", "path"), _ADD, ids=[path for _, path in _ADD]
)
def test_extra_field_is_rejected(mutate, path: str):
    document = _document()
    mutate(document)
    with pytest.raises(RunStateFormatError, match="unerlaubte Felder"):
        decode_run_state(document)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(run_id=7),
        lambda d: d.update(limits=[]),
        lambda d: d.update(state="checkpoint"),
        lambda d: d["state"].update(counters=None),
        lambda d: d["limits"].update(worker_attempts="9"),
        lambda d: d["state"]["counters"].update(worker_attempt=None),
        lambda d: d["state"].update(phase=1),
    ],
)
def test_wrongly_typed_field_is_rejected(mutate):
    document = _document()
    mutate(document)
    with pytest.raises(RunStateFormatError):
        decode_run_state(document)


# -- Enum-Werte ----------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["state"].update(phase="halted"),
        lambda d: _machine_doc(d)["escalation"].update(kind="worker"),
        lambda d: _machine_doc(d)["escalation"].update(
            resume_point="nowhere"
        ),
        lambda d: _machine_doc(d)["escalation"].update(
            cause="just_because"
        ),
    ],
)
def test_unknown_enum_value_is_rejected(mutate):
    document = _document()
    mutate(document)
    with pytest.raises(RunStateFormatError, match="unbekannter Wert"):
        decode_run_state(document)


def _machine_doc(document: dict[str, object]) -> dict[str, object]:
    document["escalation"] = encode_run_state(
        _run(escalation=_MACHINE)
    )["escalation"]
    return document


# -- bool an Integer-Stellen und umgekehrt ------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(schema_version=True),
        lambda d: d.update(revision=True),
        lambda d: d["limits"].update(worker_attempts=True),
        lambda d: d["state"]["counters"].update(worker_attempt=False),
    ],
)
def test_bool_is_not_a_count(mutate):
    document = _document()
    mutate(document)
    with pytest.raises(RunStateFormatError, match="int erwartet"):
        decode_run_state(document)


@pytest.mark.parametrize("value", [0, 1])
def test_count_is_not_a_flag(value: int):
    document = _document()
    document["state"]["checkpointed_result"] = value
    with pytest.raises(RunStateFormatError, match="bool erwartet"):
        decode_run_state(document)


# -- Nicht-Objekt an Stelle einer Eskalation ---------------------


@pytest.mark.parametrize("value", [[], False, "agent", 0])
def test_escalation_must_be_object_or_null(value: object):
    document = _document()
    document["escalation"] = value
    with pytest.raises(
        RunStateFormatError, match="JSON-Objekt erwartet"
    ):
        decode_run_state(document)


# -- Der gesamte akzeptierte Zustandsraum bleibt erhalten --------

_TEXT = st.text(
    alphabet=st.characters(min_codepoint=33, max_codepoint=126),
    min_size=1,
    max_size=12,
)
_PHASES = st.sampled_from(list(Phase))
_COUNT = st.integers(min_value=0, max_value=9)
_LIMIT = st.integers(min_value=1, max_value=9)

_ESCALATIONS = st.one_of(
    st.none(),
    st.builds(AgentEscalation, cause=_TEXT, resume_point=_PHASES),
    st.builds(
        MachineEscalation,
        cause=st.sampled_from(list(MachineEscalationCause)),
        resume_point=_PHASES,
    ),
)

_RUNS = st.builds(
    RunState,
    run_id=_TEXT,
    revision=st.integers(min_value=0, max_value=99),
    state=st.builds(
        MachineState,
        phase=_PHASES,
        counters=st.builds(
            Counters,
            protocol_attempt=_COUNT,
            worker_attempt=_COUNT,
            process_retry=_COUNT,
            changes_round=_COUNT,
        ),
        checkpointed_result=st.booleans(),
    ),
    limits=st.builds(
        Limits,
        protocol_attempts=_LIMIT,
        worker_attempts=_LIMIT,
        changes_rounds=_LIMIT,
        process_retries=_LIMIT,
    ),
    escalation=_ESCALATIONS,
)


@given(_RUNS)
@settings(max_examples=300)
def test_accepted_runs_survive_roundtrip(run: RunState):
    wire = json.dumps(encode_run_state(run))
    assert decode_run_state(json.loads(wire)) == run
