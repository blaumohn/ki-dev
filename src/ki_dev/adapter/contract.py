"""Vertrag zwischen Ausführer und Adaptern der Bau- und Review-Rolle.

Ein Adapter bekommt eine Anfrage (Auftrag, Runde, Beanstandung bzw.
Nachweis) und liefert eine formale Ausgabe: einen Baubericht oder den
Rohtext eines Review-Urteils. Wie er das tut (Claude, Codex, Mensch als
Bote, Mock), bleibt hinter diesem Vertrag verborgen; Ablaufwissen hat
er nicht.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from ki_dev.adapter.executors.contract import ExecutorSpec, TurnResult
from ki_dev.json_reply import unwrap_json_fence


class AnswerPending(Exception):
    """Die Eingabe ist übergeben, die Antwort des Transports fehlt noch
    (z. B. Bote ohne Antwort). Halt des Ausführers, kein
    Ablaufzustand: die Operation läuft nach ``resume`` erneut."""


class AgentProtocolError(ValueError):
    """Agentenausgabe verletzt den formalen Antwortvertrag."""


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

    def bead_ids(self) -> tuple[str, ...]:
        """Beads-IDs des Auftrags aus seinen Quellen ``bd:ID``."""
        return tuple(
            source[3:]
            for source in self.sources
            if source.startswith("bd:")
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
    outcome: Literal["completed", "needs_decision", "escalate"] = (
        "completed"
    )

    def __post_init__(self) -> None:
        if not isinstance(self.summary, str):
            raise ValueError("WorkReport.summary muss Text sein")
        if not self.summary.strip():
            raise ValueError("WorkReport.summary darf nicht leer sein")
        if self.outcome not in (
            "completed", "needs_decision", "escalate"
        ):
            raise ValueError("WorkReport.outcome ist ungültig")


def parse_work_report(raw: str) -> WorkReport:
    """Freitext bleibt completed; JSON-Objekte verlangen beide Felder.

    Objekt-, Array- und Codeblock-Anfänge reservieren strukturierte
    Antworten, ebenso ein Objekt am Ende nach einleitendem Text oder
    ein Feld ``"outcome"`` irgendwo im Text. Ein einziger
    umschließender Codeblock fällt weg (``unwrap_json_fence``). Fehler
    darin dürfen nie als erfolgreicher Text gelten.
    """
    text = raw.strip()
    try:
        if text.startswith(("{", "[", "```")):
            value = json.loads(
                unwrap_json_fence(text), object_pairs_hook=_work_fields
            )
        elif _embeds_report(text):
            value = _trailing_object(text)
        else:
            return WorkReport(raw)
        if not isinstance(value, dict) or set(value) != {
            "outcome", "summary"
        }:
            raise ValueError(
                "Worker-JSON verlangt genau outcome und summary"
            )
        return WorkReport(**value)
    except ValueError as exc:
        raise AgentProtocolError(str(exc)) from exc


def _embeds_report(text: str) -> bool:
    last = text.splitlines()[-1].lstrip() if text else ""
    return last.startswith("{") or '"outcome"' in text


def _trailing_object(text: str) -> object:
    """Erstes zeilenbeginnendes JSON, das bis zum Textende reicht."""
    offset = 0
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("{"):
            try:
                return json.loads(
                    text[offset:], object_pairs_hook=_work_fields
                )
            except json.JSONDecodeError:
                pass
        offset += len(line)
    raise ValueError(
        "Worker-Antwort enthält nach dem Text kein gültiges "
        "JSON-Objekt am Ende"
    )


def _work_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value = dict(pairs)
    if len(value) != len(pairs):
        raise ValueError("Worker-JSON enthält doppelte Felder")
    return value


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
    """Bau-Rolle; ``spec`` nennt Executor und deklarierte Messungen."""

    spec: ExecutorSpec

    def work(self, request: WorkRequest) -> WorkReport: ...


class Reviewer(Protocol):
    spec: ExecutorSpec

    def review(self, request: ReviewRequest) -> str: ...


@dataclass(frozen=True)
class TurnPrompt:
    """Eine Übergabe an eine Sitzung, unabhängig von Rolle und Ablauf:
    ``key`` ist die Kennung des Versuchs (bindet die Antwort),
    ``prompt`` der fertige Text aus der Deklaration des Ablaufs."""

    key: str
    prompt: str
    workdir: Path
    env: Mapping[str, str] = field(default_factory=dict)


class TurnExecutor(Protocol):
    """Bearbeitet eine Übergabe und liefert die formale Antwort als
    Text; fehlt sie noch (Bote), meldet er :class:`AnswerPending`."""

    spec: ExecutorSpec

    def ask(self, request: TurnPrompt) -> str: ...
