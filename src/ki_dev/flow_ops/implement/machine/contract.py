"""Zustands-, Ereignis- und Grenzvertrag der begrenzten V0-Maschine.

Der Vertrag beschreibt ausschliesslich Fachlichkeit, keine Ausfuehrung:
welche Zustaende es gibt, welche Ereignisse entstehen koennen, welche
Zaehler einen aktiven Zyklus begrenzen und wie eine Eskalation
beschrieben wird.

Die drei Ereignisquellen bleiben getrennt typisiert
(Quellen-Bead ki-dev-ablauf-9p4a, Planerausgabe 21):

* Controller-Ereignisse -- validiertes KI-Qualitaetsurteil
* Worker-Ereignisse -- Ausgang genau eines Worker-Turns
* Maschinenereignisse -- deterministisch von ``ki-dev`` erzeugt

Freitext ist niemals unmittelbar ein Ereignis; die Protokollschicht
erzeugt aus geprueften Agentenausgaben die Typen dieses Moduls.

Die Uebergangsentscheidung trifft python-statemachine ueber
``[statechart]`` von implement.toml (``model.advance``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import ClassVar

from ki_dev.deltas import StepDeltaAssessment
from ki_dev.flow.model import (
    FINAL_KIND,
    WAIT_KIND,
    FlowError,
    Transition,
    load_flow,
)


class Phase(StrEnum):
    """Bezeichner der Zustände von ``flow/implement.toml``.

    Nur Namen, keine Topologie: welche Kante von wo nach wo führt, steht
    allein im Ablauf. Beim Import wird geprüft, dass Enum und Ablauf
    genau dieselben Zustände nennen.
    """

    START = "start"
    CONTROLLER_STEP = "controller_step"
    WORKER_STEP_PREPARE = "worker_step_prepare"
    WORKER_STEP = "worker_step"
    CAPTURE_STEP_RESULT = "capture_step_result"
    CHECKPOINT = "checkpoint"
    WAITING_DECISION = "waiting_decision"
    FREEZE_REVIEWED_RESULT = "freeze_reviewed_result"
    FINALIZE_HISTORY = "finalize_history"
    VERIFY_FINAL_RESULT = "verify_final_result"
    FAST_FORWARD_INTEGRATE = "fast_forward_integrate"
    PASSED = "passed"
    ERROR = "error"


IMPLEMENT = load_flow("implement")

if {phase.value for phase in Phase} != set(IMPLEMENT.states):
    raise FlowError("implement.toml: Zustände passen nicht zu Phase")


def _phases_of(kind: str) -> tuple[Phase, ...]:
    return tuple(
        Phase(state.id)
        for state in IMPLEMENT.states.values()
        if state.kind == kind
    )


TERMINAL_PHASES = frozenset(_phases_of(FINAL_KIND))

WAITING_PHASES = frozenset(_phases_of(WAIT_KIND))

STOPPED_PHASES = TERMINAL_PHASES | WAITING_PHASES


class MachineEscalationCause(StrEnum):
    """Deterministische Ursache einer maschinellen Eskalation.

    Jede Ursache benennt eine ausgeschoepfte Grenze oder ein negatives
    Pruefergebnis. Ein Agentenurteil ist niemals eine dieser Ursachen.
    """

    PROTOCOL_ATTEMPTS_EXHAUSTED = "protocol_attempts_exhausted"
    WORKER_ATTEMPTS_EXHAUSTED = "worker_attempts_exhausted"
    CHANGES_ROUNDS_EXHAUSTED = "changes_rounds_exhausted"
    PROCESS_RETRIES_EXHAUSTED = "process_retries_exhausted"
    EMPTY_RESULT_UNRESOLVED = "empty_result_unresolved"
    FINAL_VERIFICATION_FAILED = "final_verification_failed"
    INTEGRATION_FAILED = "integration_failed"
    EXECUTION_GUARD = "execution_guard"
    CHECKS_FAILED = "checks_failed"


@dataclass(frozen=True)
class AgentEscalation:
    """Eskalation aus dem Urteil eines Controllers oder Workers."""

    cause: str
    resume_point: Phase

    def __post_init__(self) -> None:
        _require_text(self.cause, "AgentEscalation.cause")
        _require_phase(
            self.resume_point, "AgentEscalation.resume_point"
        )


@dataclass(frozen=True)
class MachineEscalation:
    """Eskalation aus einer deterministischen Maschinenregel."""

    cause: MachineEscalationCause
    resume_point: Phase

    def __post_init__(self) -> None:
        if not isinstance(self.cause, MachineEscalationCause):
            raise TypeError(
                "MachineEscalation.cause muss ein "
                "MachineEscalationCause sein"
            )
        _require_phase(
            self.resume_point, "MachineEscalation.resume_point"
        )


Escalation = AgentEscalation | MachineEscalation


@dataclass(frozen=True)
class Limits:
    """Feste Obergrenzen aller wiederholbaren aktiven Zyklen.

    ``changes_rounds`` gilt je begrenztem TASK, die uebrigen Grenzen
    gelten fuer den gesamten Lauf.
    """

    protocol_attempts: int = 3
    worker_attempts: int = 12
    changes_rounds: int = 5
    process_retries: int = 3

    def __post_init__(self) -> None:
        for name, value in (
            ("protocol_attempts", self.protocol_attempts),
            ("worker_attempts", self.worker_attempts),
            ("changes_rounds", self.changes_rounds),
            ("process_retries", self.process_retries),
        ):
            label = f"Limits.{name}"
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError(f"{label} muss ein echter int sein")
            if value < 1:
                raise ValueError(f"{label} muss mindestens 1 sein")


DEFAULT_LIMITS = Limits()


@dataclass(frozen=True)
class Counters:
    """Begrenzte Ressourcen eines Laufs auf zwei Reichweiten.

    ``protocol_attempt``, ``worker_attempt`` und ``process_retry`` sind
    laufweit monoton und werden nie zurueckgesetzt. Ihre Summe steht in
    :attr:`run_total`; an ihr haengt die Begrenztheit des gesamten
    Laufs (Quellen-Bead ki-dev-ablauf-9p4a, Planerausgabe 18).

    ``changes_round`` gehoert dagegen zum aktuellen TASK, nicht zum
    Lauf: ``CHANGES`` korrigiert genau den laufenden begrenzten
    Ausschnitt, waehrend ein neuer ``TASK`` einen eigenstaendig
    pruefbaren Ausschnitt eroeffnet und deshalb ein frisches
    Korrekturrundenbudget erhaelt (Quellen-Bead ki-dev-ablauf-74lc,
    Planerausgabe 1, Form C). Weil jeder neue TASK und jede
    Korrekturrunde zugleich ``worker_attempt`` verbrauchen, begrenzt
    der laufweite Zaehler auch eine Folge vieler adaptiver TASKs.
    """

    protocol_attempt: int = 0
    worker_attempt: int = 0
    process_retry: int = 0
    changes_round: int = 0

    def __post_init__(self) -> None:
        for name, value in (
            ("protocol_attempt", self.protocol_attempt),
            ("worker_attempt", self.worker_attempt),
            ("process_retry", self.process_retry),
            ("changes_round", self.changes_round),
        ):
            _require_count(value, f"Counters.{name}")

    @property
    def run_total(self) -> int:
        """Summe der laufweit monotonen Ressourcen."""
        return (
            self.protocol_attempt
            + self.worker_attempt
            + self.process_retry
        )

    def started_task(self) -> Counters:
        """Neuer begrenzter TASK: frisches Korrekturrundenbudget."""
        return replace(
            self,
            worker_attempt=self.worker_attempt + 1,
            changes_round=0,
        )

    def started_correction(self) -> Counters:
        """Weitere Korrekturrunde desselben begrenzten TASK."""
        return replace(
            self,
            worker_attempt=self.worker_attempt + 1,
            changes_round=self.changes_round + 1,
        )

    def decided(self) -> Counters:
        """Der Mensch hat entschieden: frisches Korrekturrundenbudget
        für denselben TASK; laufweite Zähler bleiben."""
        return replace(self, changes_round=0)

    def retried_process(self) -> Counters:
        """Erneuter Versuch nach einem technischen Prozessfehler."""
        return replace(self, process_retry=self.process_retry + 1)

    def retried_protocol(self) -> Counters:
        """Erneuter Versuch nach ungueltiger Agentenausgabe."""
        return replace(self, protocol_attempt=self.protocol_attempt + 1)


@dataclass(frozen=True)
class MachineState:
    """Vollstaendiger reiner Zustand des Laufs.

    ``checkpointed_result`` unterscheidet die beiden fachlich
    verschiedenen Controller-Aufrufe: die erstmalige Beauftragung ohne
    vorliegendes Ergebnis und die Pruefung eines tatsaechlich
    erfassten und gecheckpointeten Worker-Ergebnisses. Nur der zweite
    Fall traegt ein Qualitaetsurteil.
    """

    phase: Phase
    counters: Counters = field(default_factory=Counters)
    checkpointed_result: bool = False

    def __post_init__(self) -> None:
        _require_phase(self.phase, "MachineState.phase")
        if not isinstance(self.counters, Counters):
            raise TypeError(
                "MachineState.counters muessen Counters sein"
            )
        _require_bool(
            self.checkpointed_result,
            "MachineState.checkpointed_result",
        )

    @property
    def is_stopped(self) -> bool:
        """Wartender oder terminaler Zustand ohne aktiven Zyklus."""
        return self.phase in STOPPED_PHASES


@dataclass(frozen=True)
class RunState:
    """Benannter, fortgeschriebener Zustand genau eines Laufs.

    ``run_id`` identifiziert den Lauf ueber Unterbrechungen hinweg.
    ``revision`` zaehlt die Fortschreibungen desselben Laufzustands
    monoton; sie ordnet festgehaltene Staende, ist aber selbst kein
    Zaehler eines aktiven Zyklus.

    ``escalation`` traegt die zuletzt ausgeloeste Eskalation
    einschliesslich Ursache und ``resume_point``; ohne angehaltenen
    Zyklus ist sie ``None``. Eine Eskalation laesst den Ablauf im
    Quellzustand; angehalten ist der Lauf (``halted``).

    Die Formatversion gehoert nicht hierher, sondern zur
    Serialisierung (``state_json.SCHEMA_VERSION``).
    """

    run_id: str
    revision: int
    state: MachineState
    limits: Limits = DEFAULT_LIMITS
    escalation: Escalation | None = None

    def __post_init__(self) -> None:
        _require_text(self.run_id, "RunState.run_id")
        _require_count(self.revision, "RunState.revision")
        if not isinstance(self.state, MachineState):
            raise TypeError("RunState.state muss ein MachineState sein")
        if not isinstance(self.limits, Limits):
            raise TypeError("RunState.limits muessen Limits sein")
        _require_escalation(self.escalation)

    @property
    def halted(self) -> bool:
        """Der Lauf hält: Eskalation offen oder Ablauf wartend bzw.
        am Ende."""
        return self.escalation is not None or self.state.is_stopped


@dataclass(frozen=True)
class Event:
    """Basis aller typisierten Ereignisse der V0-Maschine.

    ``flow_event`` ist der Name im Ablauf (``implement.toml``),
    abgeleitet aus dem Klassennamen: ``ControllerTask`` →
    ``controller_task``. Review-Urteile des Controllers tragen
    stattdessen das Review-Ereignis des Ablaufs (``PASS`` oder eine
    Befundklasse), damit Antwort und Kante dasselbe Wort benutzen.
    """

    flow_event: ClassVar[str] = ""

    def __init_subclass__(
        cls, flow_event: str | None = None, **kwargs: object
    ) -> None:
        super().__init_subclass__(**kwargs)
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", cls.__name__)
        cls.flow_event = flow_event or snake.lower()


@dataclass(frozen=True)
class ControllerTask(Event):
    """Controller beauftragt einen begrenzten Worker-Zyklus.

    Zulaessig als erste Beauftragung und ebenso als naechster
    begrenzter Auftrag nach einem geprueften Worker-Ergebnis
    (Quellen-Bead ki-dev-ablauf-74lc, Planerausgabe 1, Form C).
    """

    task: str

    def __post_init__(self) -> None:
        _require_text(self.task, "ControllerTask.task")


@dataclass(frozen=True)
class ControllerChanges(Event, flow_event="fix"):
    """Controller beanstandet und fordert eine Korrekturrunde."""

    objection: str

    def __post_init__(self) -> None:
        _require_text(self.objection, "ControllerChanges.objection")


@dataclass(frozen=True)
class ControllerNeedsDecision(Event, flow_event="decision"):
    """Controller fehlt eine fachliche Entscheidung."""

    question: str

    def __post_init__(self) -> None:
        _require_text(self.question, "ControllerNeedsDecision.question")


@dataclass(frozen=True)
class ControllerEscalate(Event, flow_event="escalate"):
    """Controller kann nicht zuverlaessig automatisch fortfahren."""

    cause: str

    def __post_init__(self) -> None:
        _require_text(self.cause, "ControllerEscalate.cause")


@dataclass(frozen=True)
class ControllerPass(Event, flow_event="PASS"):
    """Controller nimmt das gepruefte Ergebnis fachlich an.

    ``PASS`` ist ein Qualitaetsurteil, aber kein Laufabschluss.
    """


@dataclass(frozen=True)
class WorkerCompleted(Event):
    """Worker-Turn endete normal und ohne Sonderfallmeldung.

    Das fachliche Ergebnis ist nicht die Behauptung des Workers,
    sondern die anschliessend beobachtete Wirkung.
    """


@dataclass(frozen=True)
class WorkerNeedsDecision(Event):
    """Worker fehlt eine fachliche Entscheidung."""

    question: str

    def __post_init__(self) -> None:
        _require_text(self.question, "WorkerNeedsDecision.question")


@dataclass(frozen=True)
class WorkerEscalate(Event):
    """Worker kann den Zustand nicht zuverlaessig weiterbearbeiten."""

    cause: str

    def __post_init__(self) -> None:
        _require_text(self.cause, "WorkerEscalate.cause")


@dataclass(frozen=True)
class WorkerProcessError(Event):
    """Der Worker-Turn scheiterte technisch am Prozess."""

    detail: str

    def __post_init__(self) -> None:
        _require_text(self.detail, "WorkerProcessError.detail")


@dataclass(frozen=True)
class RunStarted(Event):
    """Der Lauf beginnt mit der ersten Controller-Pruefung."""


@dataclass(frozen=True)
class WorkerInputsPrepared(Event):
    """Git- und ``bd``-/Dolt-Basisreferenzen sind festgehalten."""


@dataclass(frozen=True)
class StepResultCaptured(Event):
    """Ergebnisreferenzen und Schrittdelta sind bewertet.

    Ein leerer Delta ohne Worker-Sonderfall ist kein Erfolg. Der Fall
    :data:`StepDeltaAssessment.EMPTY_WITH_SIGNAL` ist hier
    ausgeschlossen, weil ein Worker-Sonderfall bereits ein eigenes
    Ereignis in ``WORKER_STEP`` ist.
    """

    assessment: StepDeltaAssessment

    def __post_init__(self) -> None:
        if not isinstance(self.assessment, StepDeltaAssessment):
            raise TypeError(
                "StepResultCaptured.assessment muss ein "
                "StepDeltaAssessment sein"
            )
        if self.assessment is StepDeltaAssessment.EMPTY_WITH_SIGNAL:
            raise ValueError(
                "Ein Worker-Sonderfall ist ein eigenes Ereignis, "
                "kein Bewertungsergebnis von StepResultCaptured"
            )


@dataclass(frozen=True)
class CheckpointRecorded(Event):
    """Der technische Schritt-Checkpoint ist gesetzt."""


@dataclass(frozen=True)
class ProtocolError(Event):
    """Die Agentenausgabe erfuellte den Nachrichtenvertrag nicht."""

    detail: str

    def __post_init__(self) -> None:
        _require_text(self.detail, "ProtocolError.detail")


@dataclass(frozen=True)
class ReviewedResultFrozen(Event):
    """Basis-, Review-Commit und Review-Baum sind eingefroren."""


@dataclass(frozen=True)
class HistoryFinalized(Event):
    """Die Zielgeschichte ist nach fester Regel erzeugt."""


@dataclass(frozen=True)
class FinalResultVerified(Event):
    """Ergebnis der Ziel- und Baumidentitaetspruefung.

    ``ok`` muss ein echter ``bool`` sein. Ein truthy Ersatzwert darf
    das Sicherheitsgate der Finalisierung nicht passieren koennen.
    """

    ok: bool

    def __post_init__(self) -> None:
        _require_bool(self.ok, "FinalResultVerified.ok")


@dataclass(frozen=True)
class IntegrationCompleted(Event):
    """Ergebnis der Fast-forward-Integration.

    ``ok`` muss ein echter ``bool`` sein; dies ist das letzte Gate
    vor ``PASSED``.
    """

    ok: bool

    def __post_init__(self) -> None:
        _require_bool(self.ok, "IntegrationCompleted.ok")


@dataclass(frozen=True)
class FinalizationError(Event):
    """Unerwarteter Fehler auf dem Abschlussweg."""

    detail: str

    def __post_init__(self) -> None:
        _require_text(self.detail, "FinalizationError.detail")


@dataclass(frozen=True)
class ProcessError(Event):
    """Eine Maschinenoperation außerhalb des Worker-Turns scheiterte
    technisch (Vorbereitung, Nachweis, Review-Aufruf)."""

    detail: str

    def __post_init__(self) -> None:
        _require_text(self.detail, "ProcessError.detail")


@dataclass(frozen=True)
class ExecutionStopped(Event):
    """Der Ausführer hält aus technischem Schutz an (Kontext- oder
    Kontingentgrenze, fehlgeschlagener Agentenaufruf)."""

    detail: str

    def __post_init__(self) -> None:
        _require_text(self.detail, "ExecutionStopped.detail")


@dataclass(frozen=True)
class ResumeRequested(Event):
    """Der Mensch hat entschieden; wohin es weitergeht, sagt der
    Ablauf (aus ``waiting_decision``)."""


@dataclass(frozen=True)
class DecisionTaken(Event):
    """Fortsetzen mit Entscheidung des Menschen (Antwort oder
    geänderter Auftrag), nach jedem Halt; der Ablauf bleibt im
    Zustand, in dem er fortsetzt."""


@dataclass(frozen=True)
class TransitionResult:
    """Angenommener Uebergang: Folgezustand, ggf. Eskalation und die
    genommene Kante des Ablaufs (fuer das Ereignisprotokoll)."""

    state: MachineState
    escalation: Escalation | None = None
    transition: Transition | None = None

    @property
    def phase(self) -> Phase:
        return self.state.phase


class InvalidTransition(Exception):
    """Sichtbare Abweisung eines nicht erlaubten Uebergangs."""

    def __init__(self, state: MachineState, event: Event) -> None:
        self.state = state
        self.event = event
        super().__init__(
            f"{type(event).__name__} ist in "
            f"{state.phase.value} nicht erlaubt"
        )


def _require_text(value: str, label: str) -> None:
    """Pflichtangabe: vorhandener, nicht leerer Text."""
    if not isinstance(value, str):
        raise TypeError(f"{label} muss ein str sein")
    if not value.strip():
        raise ValueError(f"{label} darf nicht leer sein")


def _require_bool(value: object, label: str) -> None:
    """Pflichtangabe: echter ``bool``, kein truthy Ersatzwert."""
    if not isinstance(value, bool):
        raise TypeError(f"{label} muss ein echter bool sein")


def _require_phase(value: object, label: str) -> None:
    """Pflichtangabe: getippte Phase, kein roher Wert."""
    if not isinstance(value, Phase):
        raise TypeError(f"{label} muss eine Phase sein")


def _require_count(value: object, label: str) -> None:
    """Pflichtangabe: nicht negative Anzahl, kein ``bool``."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} muss ein echter int sein")
    if value < 0:
        raise ValueError(f"{label} darf nicht negativ sein")


def _require_escalation(value: object) -> None:
    """Pflichtangabe: getippte Eskalation oder klares Fehlen."""
    if value is None:
        return
    if not isinstance(value, AgentEscalation | MachineEscalation):
        raise TypeError(
            "RunState.escalation muss eine AgentEscalation oder "
            "MachineEscalation sein"
        )
