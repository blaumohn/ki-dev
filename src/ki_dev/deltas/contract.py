"""Vertrag fuer Git- und ``bd``-/Dolt-Schrittdeltas.

Die Orchestrator-Abstraktion aus Quellen-Beads ki-dev-ablauf-8ysk und ki-dev-ablauf-rdcs
ist fuer beide Wahrheiten gleich:

    Basisreferenz -> ein Worker-Schritt -> Ergebnisreferenz -> Delta

``step_delta`` und ``run_delta`` bleiben getrennte Sichten desselben
Aufbaus: der Schrittdelta betrifft genau die aktuelle Worker-Runde, der
Laufdelta die kumulierte Wirkung seit Laufbeginn.

Kein Typ dieses Moduls traegt ein ``success``- oder ``ok``-Merkmal. Ein
leerer Delta ist ausdruecklich kein Erfolgsurteil (Planerausgabe 15);
seine Bewertung erfolgt in ``step_delta.assess_step_delta``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChangeMedium(StrEnum):
    """Versionierte Wahrheit, aus der ein Delta stammt."""

    GIT = "git"
    BEADS = "beads"


class DeltaScope(StrEnum):
    """Sicht auf einen Delta: aktuelle Runde oder gesamter Lauf."""

    STEP = "step"
    RUN = "run"


class WorkerSignal(StrEnum):
    """Vom Worker gemeldeter Sonderfall des abgeschlossenen Schritts."""

    NEEDS_DECISION = "needs_decision"
    ESCALATE = "escalate"


class StepDeltaAssessment(StrEnum):
    """Ergebnis der No-op-/Ergebnispruefung eines Schrittdeltas."""

    EFFECTIVE = "effective"
    EMPTY_WITH_SIGNAL = "empty_with_signal"
    EMPTY_UNEXPLAINED = "empty_unexplained"


@dataclass(frozen=True)
class VcsRef:
    """Eine versionierte Referenz (Git-Commit oder Dolt-Commit)."""

    medium: ChangeMedium
    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("VcsRef.value darf nicht leer sein")


@dataclass(frozen=True)
class MediaRefs:
    """Git- und ``bd``-/Dolt-Referenz zum selben Zeitpunkt."""

    git: VcsRef
    beads: VcsRef

    def __post_init__(self) -> None:
        if self.git.medium is not ChangeMedium.GIT:
            raise ValueError("git-Referenz hat falsches Medium")
        if self.beads.medium is not ChangeMedium.BEADS:
            raise ValueError("beads-Referenz hat falsches Medium")


@dataclass(frozen=True)
class RefBoundary:
    """Basis- und Ergebnisreferenz eines Mediums fuer einen Delta."""

    base: VcsRef
    result: VcsRef

    def __post_init__(self) -> None:
        if self.base.medium is not self.result.medium:
            raise ValueError(
                "Basis und Ergebnis haben verschiedene Medien"
            )

    @property
    def medium(self) -> ChangeMedium:
        return self.base.medium


@dataclass(frozen=True)
class GitFileChange:
    """Eine geaenderte Datei aus ``git diff --name-status``."""

    status: str
    path: str


@dataclass(frozen=True)
class GitDelta:
    """Git-Schritt- oder -Laufdelta zwischen zwei Commit-Referenzen."""

    boundary: RefBoundary
    files: tuple[GitFileChange, ...]
    patch: str

    @property
    def is_empty(self) -> bool:
        return not self.files


@dataclass(frozen=True)
class BeadsIssueChange:
    """Ein von ``bd diff`` gemeldeter Issue-Unterschied."""

    issue_id: str
    change_type: str


@dataclass(frozen=True)
class BeadsDelta:
    """``bd``-/Dolt-Delta aus ``bd diff FROM_REF TO_REF``."""

    boundary: RefBoundary
    issues: tuple[BeadsIssueChange, ...]
    summary: str

    @property
    def is_empty(self) -> bool:
        return not self.issues


@dataclass(frozen=True)
class CombinedDelta:
    """Getrennter Git- und ``bd``-/Dolt-Delta einer Sicht."""

    scope: DeltaScope
    git: GitDelta
    beads: BeadsDelta

    @property
    def is_empty(self) -> bool:
        return self.git.is_empty and self.beads.is_empty
