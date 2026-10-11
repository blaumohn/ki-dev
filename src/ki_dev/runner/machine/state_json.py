"""JSON-Vertrag des versionierten Laufzustands.

:func:`encode_run_state` und :func:`decode_run_state` sind zueinander
inverse Abbildungen zwischen :class:`RunState` und einer rein
JSON-faehigen Struktur aus ``dict``, ``str``, ``int``, ``bool`` und
``None``. Der Roundtrip erhaelt alle Werte und beide konkreten
Eskalationstypen.

Aufbau eines Dokuments::

    {
      "schema_version": 3,
      "run_id": "...",
      "revision": 0,
      "limits": {protocol_attempts, worker_attempts,
                 changes_rounds, process_retries},
      "state": {"phase": "...",
                "counters": {protocol_attempt, worker_attempt,
                             process_retry, changes_round},
                "checkpointed_result": false,
                "history": null | "..."},
      "escalation": null | {"kind": "agent" | "machine",
                            "cause": "...",
                            "resume_point": "..."}
    }

``kind`` unterscheidet die beiden Eskalationstypen und bestimmt
zugleich die Lesart von ``cause``: freier Agententext gegenueber genau
einer :class:`MachineEscalationCause`. Abgeleitete Groessen wie
``Counters.run_total`` werden nicht geschrieben; sie entstehen beim
Lesen wieder aus den Zaehlern selbst.

Gelesen wird ausschliesslich streng. Eine unbekannte Formatversion,
ein unbekannter Enum-Wert, ein fehlendes, zusaetzliches oder falsch
getipptes Feld sowie ein ``bool`` an Stelle einer Anzahl fuehren zu
:class:`RunStateFormatError`. Es gibt keinen stillen Standardwert und
keinen Rueckfall auf einen Ersatzwert.

Diese Schicht prueft die Form des Dokuments. Fachliche Regeln --
nicht leerer Text, Mindestgrenzen, nicht negative Zaehler -- bleiben
Sache der Typen in ``contract``; ihre Verletzung wird dort sichtbar
abgewiesen.
"""

from __future__ import annotations

from enum import StrEnum

from .contract import (
    AgentEscalation,
    Counters,
    Escalation,
    Limits,
    MachineEscalation,
    MachineEscalationCause,
    MachineState,
    Phase,
    RunState,
)

# 3: Fortsetzungspunkt als History im Zustand (python-statemachine,
# ki-dev-ablauf-9cn.2); ältere Läufe werden abgelehnt, nicht migriert.
SCHEMA_VERSION = 3

JsonObject = dict[str, object]

_RUN_PATH = "run_state"
_LIMITS_PATH = f"{_RUN_PATH}.limits"
_STATE_PATH = f"{_RUN_PATH}.state"
_COUNTERS_PATH = f"{_STATE_PATH}.counters"
_ESCALATION_PATH = f"{_RUN_PATH}.escalation"

_RUN_FIELDS = (
    "schema_version",
    "run_id",
    "revision",
    "limits",
    "state",
    "escalation",
)
_LIMITS_FIELDS = (
    "protocol_attempts",
    "worker_attempts",
    "changes_rounds",
    "process_retries",
)
_STATE_FIELDS = (
    "phase",
    "counters",
    "checkpointed_result",
    "history",
)
_COUNTERS_FIELDS = (
    "protocol_attempt",
    "worker_attempt",
    "process_retry",
    "changes_round",
)
_ESCALATION_FIELDS = ("kind", "cause", "resume_point")


class EscalationKind(StrEnum):
    """Im JSON festgehaltener konkreter Eskalationstyp."""

    AGENT = "agent"
    MACHINE = "machine"


class RunStateFormatError(ValueError):
    """Sichtbare Abweisung eines ungueltigen Laufzustand-Dokuments."""


def encode_run_state(run: RunState) -> JsonObject:
    """Wandle den Laufzustand in die JSON-Struktur dieses Vertrags."""
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run.run_id,
        "revision": run.revision,
        "limits": _encode_limits(run.limits),
        "state": _encode_state(run.state),
        "escalation": _encode_escalation(run.escalation),
    }


def decode_run_state(document: object) -> RunState:
    """Lies ein vollstaendiges Dokument in die getippten Laufdaten."""
    fields = _object_fields(document, _RUN_FIELDS, _RUN_PATH)
    _require_known_schema(fields["schema_version"])
    return RunState(
        run_id=_text(fields["run_id"], f"{_RUN_PATH}.run_id"),
        revision=_count(fields["revision"], f"{_RUN_PATH}.revision"),
        state=_decode_state(fields["state"]),
        limits=_decode_limits(fields["limits"]),
        escalation=_decode_escalation(fields["escalation"]),
    )


def _encode_limits(limits: Limits) -> JsonObject:
    return {
        "protocol_attempts": limits.protocol_attempts,
        "worker_attempts": limits.worker_attempts,
        "changes_rounds": limits.changes_rounds,
        "process_retries": limits.process_retries,
    }


def _encode_state(state: MachineState) -> JsonObject:
    return {
        "phase": state.phase.value,
        "counters": _encode_counters(state.counters),
        "checkpointed_result": state.checkpointed_result,
        "history": (
            None if state.history is None else state.history.value
        ),
    }


def _encode_counters(counters: Counters) -> JsonObject:
    """Nur die gezaehlten Ressourcen, nicht ihre Summe."""
    return {
        "protocol_attempt": counters.protocol_attempt,
        "worker_attempt": counters.worker_attempt,
        "process_retry": counters.process_retry,
        "changes_round": counters.changes_round,
    }


def _encode_escalation(
    escalation: Escalation | None,
) -> JsonObject | None:
    if escalation is None:
        return None
    kind, cause = _escalation_kind_and_cause(escalation)
    return {
        "kind": kind.value,
        "cause": cause,
        "resume_point": escalation.resume_point.value,
    }


def _escalation_kind_and_cause(
    escalation: Escalation,
) -> tuple[EscalationKind, str]:
    """Ordne dem Eskalationstyp seine JSON-Ursache zu."""
    if isinstance(escalation, AgentEscalation):
        return EscalationKind.AGENT, escalation.cause
    if isinstance(escalation, MachineEscalation):
        return EscalationKind.MACHINE, escalation.cause.value
    raise TypeError(
        f"unbekannter Eskalationstyp {type(escalation).__name__}"
    )


def _decode_state(value: object) -> MachineState:
    fields = _object_fields(value, _STATE_FIELDS, _STATE_PATH)
    return MachineState(
        phase=_enum_member(
            Phase, fields["phase"], f"{_STATE_PATH}.phase"
        ),
        counters=_decode_counters(fields["counters"]),
        checkpointed_result=_flag(
            fields["checkpointed_result"],
            f"{_STATE_PATH}.checkpointed_result",
        ),
        history=(
            None
            if fields["history"] is None
            else _enum_member(
                Phase, fields["history"], f"{_STATE_PATH}.history"
            )
        ),
    )


def _decode_counters(value: object) -> Counters:
    fields = _object_fields(value, _COUNTERS_FIELDS, _COUNTERS_PATH)
    return Counters(**_counts(fields, _COUNTERS_PATH))


def _decode_limits(value: object) -> Limits:
    fields = _object_fields(value, _LIMITS_FIELDS, _LIMITS_PATH)
    return Limits(**_counts(fields, _LIMITS_PATH))


def _decode_escalation(value: object) -> Escalation | None:
    """Erzeuge wieder genau den in ``kind`` benannten Typ."""
    if value is None:
        return None
    fields = _object_fields(value, _ESCALATION_FIELDS, _ESCALATION_PATH)
    kind = _enum_member(
        EscalationKind, fields["kind"], f"{_ESCALATION_PATH}.kind"
    )
    resume_point = _enum_member(
        Phase,
        fields["resume_point"],
        f"{_ESCALATION_PATH}.resume_point",
    )
    cause_path = f"{_ESCALATION_PATH}.cause"
    if kind is EscalationKind.AGENT:
        return AgentEscalation(
            cause=_text(fields["cause"], cause_path),
            resume_point=resume_point,
        )
    return MachineEscalation(
        cause=_enum_member(
            MachineEscalationCause, fields["cause"], cause_path
        ),
        resume_point=resume_point,
    )


def _require_known_schema(value: object) -> None:
    """Genau die eine bekannte Formatversion wird gelesen."""
    version = _count(value, f"{_RUN_PATH}.schema_version")
    if version != SCHEMA_VERSION:
        raise RunStateFormatError(
            f"{_RUN_PATH}.schema_version: {version} wird nicht "
            f"unterstuetzt, erwartet {SCHEMA_VERSION}"
        )


def _object_fields(
    value: object,
    names: tuple[str, ...],
    path: str,
) -> JsonObject:
    """Genau die erwarteten Felder eines JSON-Objekts, sonst Fehler."""
    if not isinstance(value, dict):
        raise RunStateFormatError(f"{path}: JSON-Objekt erwartet")
    missing = [name for name in names if name not in value]
    if missing:
        raise RunStateFormatError(f"{path}: fehlende Felder {missing}")
    extra = sorted(str(key) for key in value if key not in names)
    if extra:
        raise RunStateFormatError(f"{path}: unerlaubte Felder {extra}")
    return value


def _counts(fields: JsonObject, path: str) -> dict[str, int]:
    """Alle Felder eines reinen Zaehlerobjekts als ``int``."""
    return {
        name: _count(value, f"{path}.{name}")
        for name, value in fields.items()
    }


def _text(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise RunStateFormatError(f"{path}: str erwartet")
    return value


def _count(value: object, path: str) -> int:
    """``int`` ohne ``bool``: ein Wahrheitswert ist keine Anzahl."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise RunStateFormatError(f"{path}: int erwartet")
    return value


def _flag(value: object, path: str) -> bool:
    """Echter ``bool``: ``0`` und ``1`` sind hier kein Flag."""
    if not isinstance(value, bool):
        raise RunStateFormatError(f"{path}: bool erwartet")
    return value


def _enum_member[E: StrEnum](
    members: type[E],
    value: object,
    path: str,
) -> E:
    """Genau ein bekannter Enum-Wert, sonst sichtbare Abweisung."""
    text = _text(value, path)
    try:
        return members(text)
    except ValueError as unknown:
        raise RunStateFormatError(
            f"{path}: unbekannter Wert {text!r}"
        ) from unknown
