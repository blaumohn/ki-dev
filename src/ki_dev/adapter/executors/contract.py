"""Executor-unabhaengiger Vertrag fuer genau einen Agenten-Turn.

Die Kontrollschleife kennt nur die Typen dieses Moduls. Sie kennt
weder Claude- noch Codex-spezifische Argumente. Ein Turn ist genau
ein synchroner Prozessaufruf; sein Ende ist die Schrittgrenze.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable

from ki_dev.usage import UsageEvent


class Effort(StrEnum):
    """Angeforderter Denkaufwand fuer einen Turn."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Measure(StrEnum):
    """Messung, die ein Transport umsetzt und ein Executor deklariert.

    ``budget`` heisst: der Aufruf wird im Laufbudget gebucht
    (Reservierung, Aufrufzahl, Verbrauch, Kosten).
    """

    CONTEXT = "context"
    QUOTA = "quota"
    BUDGET = "budget"


@dataclass(frozen=True)
class ExecutorSpec:
    """Deklarierter Executor: Name, Transport und Messungen, die der
    Ausführer verlangt (``adapter/executors.toml``)."""

    name: str
    transport: str
    measures: frozenset[Measure]


class TurnStatus(StrEnum):
    """Eindeutiger Ausgang eines Turn-Prozesses.

    Die vier Werte sind bewusst disjunkt, damit Fehler- und
    Timeoutfaelle nie zusammenfallen und nie stillschweigend als
    Erfolg gelten.
    """

    OK = "ok"
    NONZERO_EXIT = "nonzero_exit"
    TIMEOUT = "timeout"
    START_ERROR = "start_error"


@dataclass(frozen=True)
class TurnBudget:
    """Grenzen eines CLI-Aufrufs.

    ``max_usage_delta_percentage_points`` ist die einzige Ausnahme:
    das erlaubte Wachstum des beobachteten Fuenfstundenkontingents
    dieser Rolle seit ihrer Baseline (``runner.safety.QuotaBaseline``),
    in Prozentpunkten -- ein kontoweiter, konservativer Naeherungswert
    fuer den Verbrauch dieser Aufgabe, keine exakte Zurechnung (siehe
    ``runner.runtime._quota_guard``, ki-dev-ablauf-dqv).
    """

    max_turns: int = 12
    max_budget_usd: float = 1.0
    max_context_tokens: int = 80_000
    timeout_s: float = 180.0
    max_usage_delta_percentage_points: float = 20.0

    def __post_init__(self) -> None:
        for name in ("max_turns", "max_context_tokens"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(
                    f"{name} muss eine positive Ganzzahl sein"
                )
        for name in ("max_budget_usd", "timeout_s"):
            value = getattr(self, name)
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(
                    f"{name} muss positiv und endlich sein"
                )
        delta = self.max_usage_delta_percentage_points
        if (
            type(delta) not in (int, float)
            or not math.isfinite(delta)
            or not (0 < delta <= 100)
        ):
            raise ValueError(
                "max_usage_delta_percentage_points muss in "
                "(0, 100] Prozentpunkten liegen"
            )


@dataclass(frozen=True)
class TurnRequest:
    """Eingabe fuer einen einzelnen synchronen Turn.

    ``workdir`` und ``env`` binden den Kindprozess technisch an den
    konfigurierten Worktree, statt sich auf Pfadangaben im Prompt zu
    verlassen: der Agent liest und schreibt Dateien relativ zu
    ``workdir``, und ``env`` ueberschreibt gezielt geerbte
    Umgebungsvariablen (z. B. eine fremde ``PYTHONPATH``), die sonst
    stillschweigend auf einen anderen Quellstand zeigen koennten.
    """

    session_id: str
    message: str
    model: str
    effort: Effort
    workdir: Path
    env: dict[str, str] = field(default_factory=dict)
    budget: TurnBudget | None = None

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("session_id darf nicht leer sein")
        if not self.message:
            raise ValueError("message darf nicht leer sein")
        if not self.model:
            raise ValueError("model darf nicht leer sein")
        if not isinstance(self.effort, Effort):
            raise TypeError("effort muss ein Effort-Wert sein")
        if not self.workdir.is_absolute():
            raise ValueError("workdir muss absolut sein")
        if not isinstance(self.env, dict) or any(
            not isinstance(k, str) or not k or not isinstance(v, str)
            for k, v in self.env.items()
        ):
            raise TypeError(
                "env muss ein Mapping von Text auf Text sein"
            )
        if self.budget is not None and not isinstance(
            self.budget, TurnBudget
        ):
            raise TypeError("budget muss ein TurnBudget sein")


class ContextStatus(StrEnum):
    """Herkunft eines Kontextmesswerts, disjunkt von der Zahl selbst.

    Eine fehlende oder nicht unterstuetzte Messung ist damit technisch
    von einem tatsaechlich gemessenen kleinen Kontext unterscheidbar;
    keiner der beiden Faelle darf als ``0`` durchgereicht werden.
    """

    MEASURED = "measured"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ContextMeasurement:
    """Sitzungsbezogener Kontextmesswert eines Executors.

    ``UNSUPPORTED`` heisst: dieser Executor bietet grundsaetzlich
    keine Kontextmessung (z. B. Codex, siehe ``docs/cli-adapters.md``).
    ``UNAVAILABLE`` heisst: eine Messung ist vorgesehen, aber fuer
    diese Sitzung gerade nicht lesbar (fehlende, mehrdeutige oder
    ungueltige lokale Ablage). Nur ``MEASURED`` traegt ``tokens``.
    """

    status: ContextStatus
    tokens: int | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, ContextStatus):
            raise TypeError(
                "ContextMeasurement.status muss ein ContextStatus sein"
            )
        if self.status is ContextStatus.MEASURED:
            if (
                isinstance(self.tokens, bool)
                or not isinstance(self.tokens, int)
                or self.tokens < 0
            ):
                raise ValueError(
                    "ContextMeasurement.tokens muss bei MEASURED "
                    "eine nicht negative Ganzzahl sein"
                )
        elif self.tokens is not None:
            raise ValueError(
                "ContextMeasurement.tokens ist nur bei MEASURED erlaubt"
            )


class QuotaStatus(StrEnum):
    """Herkunft eines Fuenfstundenkontingent-Messwerts.

    Anders als ``ContextStatus`` gibt es hier keinen Status, der einen
    Aufruf freigibt, ausser einem tatsaechlichen Messwert unter der
    Grenze: fuer das Kontokontingent gibt es keine sichere Annahme
    "klein/unbekannt = ok" wie bei einem kurzen Sitzungskontext.
    ``UNSUPPORTED`` heisst deshalb hier nicht "kein Blocker", sondern
    "dieser Executor liefert (noch) keinen Nachweis" -- die
    Orchestrierung haelt in beiden Nicht-MEASURED-Faellen an
    (ki-dev-ablauf-hju).

    Einzige Ausnahme ist ``PENDING``: Der Adapter misst erst mit der
    Antwort eines Aufrufs (claude-cli: ``rate_limit_event``) und hat
    fuer diese Sitzung noch keinen Wert. Der erste Aufruf laeuft
    ungemessen; ab dem zweiten gilt wieder ``MEASURED``. Ein Adapter
    ohne diese Faehigkeit liefert ``PENDING`` nie.
    """

    MEASURED = "measured"
    PENDING = "pending"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class QuotaMeasurement:
    """Kontobezogener Fuenfstundenkontingent-Messwert eines Executors.

    ``used_percent`` ist der Anteil des rollierenden
    Fuenfstundenfensters, den das Konto laut Executor bereits
    verbraucht hat (0..100), nicht ein aus Tokenzahlen geschaetzter
    Wert. ``resets_at`` (Unix-Sekunden) identifiziert das Fenster
    dieses Messwerts und macht einen Fensterrollover erkennbar (siehe
    ``runner.safety.QuotaBaseline``). Nur ``MEASURED`` traegt beide
    Felder; ein veralteter Messwert (``resets_at`` in der
    Vergangenheit) zaehlt nicht als ``MEASURED`` mit ``0``, sondern als
    ``UNAVAILABLE`` (siehe Adapterimplementierung).
    """

    status: QuotaStatus
    used_percent: float | None = None
    resets_at: int | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, QuotaStatus):
            raise TypeError(
                "QuotaMeasurement.status muss ein QuotaStatus sein"
            )
        if self.status is QuotaStatus.MEASURED:
            if (
                type(self.used_percent) not in (int, float)
                or not math.isfinite(self.used_percent)
                or self.used_percent < 0
            ):
                raise ValueError(
                    "QuotaMeasurement.used_percent muss bei MEASURED "
                    "eine nicht negative, endliche Zahl sein"
                )
            if type(self.resets_at) is not int:
                raise ValueError(
                    "QuotaMeasurement.resets_at muss bei MEASURED "
                    "eine Ganzzahl sein"
                )
        else:
            if self.used_percent is not None:
                raise ValueError(
                    "QuotaMeasurement.used_percent ist nur bei "
                    "MEASURED erlaubt"
                )
            if self.resets_at is not None:
                raise ValueError(
                    "QuotaMeasurement.resets_at ist nur bei MEASURED "
                    "erlaubt"
                )


@dataclass(frozen=True)
class TurnResult:
    """Einheitliches Ergebnis eines Turn-Prozesses.

    ``stdout``, ``stderr``, ``exit_code`` und ``argv`` werden fuer
    jeden Ausgang gleich befuellt, soweit verfuegbar. ``error``
    traegt bei jedem Nicht-Erfolg eine erklaerende Meldung.
    Bei budgetierten Aufrufen enthaelt ``stdout`` die extrahierte
    Agentenantwort; ``usage`` enthaelt den gemeldeten Verbrauch.
    """

    status: TurnStatus
    exit_code: int | None
    stdout: str
    stderr: str
    argv: tuple[str, ...]
    duration_s: float
    error: str | None = None
    usage: dict[str, int | float] | None = None
    # Normalisierter Gegenwert zu ``usage`` (ki-dev-ablauf-wu0.3):
    # dieselbe rohe Provider-Antwort, nur ueber den versionierten
    # Messvertrag aus ``ki_dev.usage`` normalisiert, statt ueber das
    # hiesige Ad-hoc-Feldschema. Beide beschreiben denselben Turn und
    # duerfen sich nie widersprechen.
    usage_event: UsageEvent | None = None

    @property
    def ok(self) -> bool:
        return self.status is TurnStatus.OK


@runtime_checkable
class Executor(Protocol):
    """Oeffentlicher Turn-Vertrag, den beide Adapter erfuellen;
    ``capabilities`` nennt die Messungen, die der Transport umsetzt."""

    name: str
    capabilities: frozenset[Measure]

    def send_turn(self, request: TurnRequest) -> TurnResult: ...

    def measure_context(
        self, session_id: str
    ) -> ContextMeasurement: ...

    def measure_quota(self, session_id: str) -> QuotaMeasurement: ...
