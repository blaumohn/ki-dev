"""Vertrag zwischen Ausführer und Adaptern der Bau- und Review-Rolle.

Ein Adapter bekommt eine Anfrage (Auftrag, Runde, Beanstandung bzw.
Nachweis) und liefert eine formale Ausgabe: einen Baubericht oder den
Rohtext eines Review-Urteils. Wie er das tut (Claude, Codex, Mensch als
Bote, Mock), bleibt hinter diesem Vertrag verborgen; Ablaufwissen hat
er nicht.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ki_dev.adapter.executors.contract import TurnResult


class AgentTurnError(RuntimeError):
    """Agentenaufruf ohne Erlaubnis zur automatischen Wiederholung."""

    def __init__(self, result: TurnResult) -> None:
        self.result = result
        super().__init__(
            "; ".join(
                filter(
                    None,
                    (
                        result.error or result.status.value,
                        result.stderr[:2000],
                    ),
                )
            )
        )


@dataclass(frozen=True)
class RunTask:
    run_id: str
    task: str
    sources: tuple[str, ...]
    workdir: Path
    access_profile: str
    acceptance_criteria: tuple[str, ...] = field(kw_only=True)
    env: dict[str, str] = field(kw_only=True, default_factory=dict)

    def __post_init__(self) -> None:
        for name, value in (
            ("run_id", self.run_id),
            ("task", self.task),
            ("access_profile", self.access_profile),
        ):
            if not value.strip():
                raise ValueError(
                    f"RunTask.{name} darf nicht leer sein"
                )
        if not self.workdir.is_absolute():
            raise ValueError("RunTask.workdir muss absolut sein")
        if not isinstance(self.sources, tuple) or any(
            not isinstance(source, str) or not source.strip()
            for source in self.sources
        ):
            raise TypeError(
                "RunTask.sources muss ein Tupel nichtleerer Texte sein"
            )
        if not isinstance(
            self.acceptance_criteria, tuple
        ) or any(
            not isinstance(item, str) or not item.strip()
            for item in self.acceptance_criteria
        ):
            raise TypeError(
                "RunTask.acceptance_criteria muss ein Tupel "
                "nichtleerer Texte sein"
            )
        if not self.acceptance_criteria:
            raise ValueError(
                "RunTask.acceptance_criteria darf nicht leer sein"
            )
        if len(set(self.acceptance_criteria)) != len(
            self.acceptance_criteria
        ):
            raise ValueError(
                "RunTask.acceptance_criteria muss eindeutig sein"
            )
        if not isinstance(self.env, dict) or any(
            not isinstance(k, str) or not k or not isinstance(v, str)
            for k, v in self.env.items()
        ):
            raise TypeError(
                "RunTask.env muss ein Mapping von Text auf Text sein"
            )

    def acceptance_criterion_ref(self, index: int) -> str:
        return f"AC{index}"

    def acceptance_criterion_refs(self) -> tuple[str, ...]:
        return tuple(
            self.acceptance_criterion_ref(i)
            for i in range(1, len(self.acceptance_criteria) + 1)
        )


@dataclass(frozen=True)
class WorkRequest:
    """Auftrag an die Worker-Rolle; ``prompt`` hat der Ausführer aus
    der Vorlage des Ablaufs gebildet, der Adapter transportiert ihn."""

    task: RunTask
    round_id: int
    prompt: str
    attempt_id: str
    """Eindeutig je Versuch (auch je Protokollwiederholung); bindet
    eine Antwort des Boten an genau diesen Versuch."""


@dataclass(frozen=True)
class WorkReport:
    summary: str

    def __post_init__(self) -> None:
        if not self.summary.strip():
            raise ValueError("BuildReport.summary darf nicht leer sein")


@dataclass(frozen=True)
class ReviewVocabulary:
    """Erlaubte Review-Antworten, vom Ausführer aus dem Ablauf gebildet
    (Adapter kennen keinen Ablauf).

    ``events`` beginnt mit PASS; ``changes`` verlangt eine
    Kriteriumsbindung, ``unbound`` ersetzt es ohne Bindung; ``texts``
    erklärt jede Befundklasse."""

    events: tuple[str, ...]
    changes: str
    unbound: str
    texts: Mapping[str, str]


@dataclass(frozen=True)
class ReviewRequest:
    """Auftrag an die Review-Rolle; ``prompt`` wie bei WorkRequest,
    ``vocabulary`` für Adapter, die selbst antworten (mock)."""

    task: RunTask
    round_id: int
    prompt: str
    vocabulary: ReviewVocabulary
    attempt_id: str


class Worker(Protocol):
    def work(self, request: WorkRequest) -> WorkReport: ...


class Reviewer(Protocol):
    def review(self, request: ReviewRequest) -> str: ...
