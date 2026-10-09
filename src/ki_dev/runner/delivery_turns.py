"""Eingaben an die Sitzungen des Lieferablaufs, aus Vorlagen.

``delivery.toml`` deklariert Vorlage und Kontext der Operationen
``work`` und ``review``; die Rollentexte stehen unter
``flow/templates/delivery/``. Der Ausführer rendert sie über
dieselbe Funktion wie der Planungsablauf (:mod:`ki_dev.runner.turns`)
und gibt den fertigen Prompt im Auftrag an den Adapter. Claude, Codex
und der Mensch als Bote erhalten denselben Wortlaut; Adapter kennen
weder Ablauf noch Vorlagen.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ki_dev.adapter.contract import ReviewVocabulary, RunTask
from ki_dev.flow.model import FlowError, Turn
from ki_dev.review_context import ReviewProjection
from ki_dev.runner.machine import DELIVERY
from ki_dev.runner.turns import Plug, bind_turns, render_turn

WORK = "work"
REVIEW = "review"


@dataclass(frozen=True)
class DeliveryTurn:
    """Eingabe der Felder einer Übergabe des Lieferablaufs."""

    task: RunTask
    round_id: int
    objection: str | None = None
    report: str = ""
    evidence: ReviewProjection | None = None
    vocabulary: ReviewVocabulary | None = None


def _vocabulary(turn: DeliveryTurn) -> ReviewVocabulary:
    if turn.vocabulary is None:
        raise FlowError("Review-Übergabe braucht das Vokabular")
    return turn.vocabulary


def _criteria(turn: DeliveryTurn) -> str:
    task = turn.task
    return "\n".join(
        f"- {ref}: {text}"
        for ref, text in zip(
            task.acceptance_criterion_refs(),
            task.acceptance_criteria,
            strict=True,
        )
    )


def _classes(turn: DeliveryTurn) -> str:
    texts = _vocabulary(turn).texts
    return "\n".join(
        f"- {name}: {text}" for name, text in texts.items()
    )


def _evidence(turn: DeliveryTurn) -> str:
    if turn.evidence is None:
        raise FlowError("Review-Übergabe braucht die Nachweise")
    return turn.evidence.text


FIELDS: dict[str, Callable[[DeliveryTurn], object]] = {
    "run_id": lambda turn: turn.task.run_id,
    "round_id": lambda turn: turn.round_id,
    "workdir": lambda turn: turn.task.workdir,
    "access_profile": lambda turn: turn.task.access_profile,
    "criteria": _criteria,
    "sources": lambda turn: (
        "\n".join(f"- {source}" for source in turn.task.sources)
        or "- keine"
    ),
    "task": lambda turn: turn.task.task,
    "objection": lambda turn: turn.objection or "keine",
    "report": lambda turn: turn.report,
    "evidence": _evidence,
    "classes": _classes,
    "events": lambda turn: "|".join(_vocabulary(turn).events),
    "changes": lambda turn: _vocabulary(turn).changes,
    "unbound": lambda turn: _vocabulary(turn).unbound,
}
PLUG: Plug[DeliveryTurn] = Plug(FIELDS, {})
bind_turns(DELIVERY, PLUG, (WORK, REVIEW))


def _declared(operation: str) -> Turn:
    """Die Übergabe der Operation laut ``delivery.toml``."""
    for state in DELIVERY.states.values():
        for candidate in state.operations:
            if candidate.do == operation and candidate.turn:
                return candidate.turn
    raise LookupError(operation)


def work_prompt(
    task: RunTask, round_id: int, objection: str | None
) -> str:
    subject = DeliveryTurn(task, round_id, objection)
    turn = _declared(WORK)
    return render_turn(DELIVERY, turn, subject, PLUG).text()


def review_prompt(
    task: RunTask,
    round_id: int,
    report: str,
    evidence: ReviewProjection,
    vocabulary: ReviewVocabulary,
) -> str:
    subject = DeliveryTurn(
        task, round_id, None, report, evidence, vocabulary
    )
    turn = _declared(REVIEW)
    return render_turn(DELIVERY, turn, subject, PLUG).text()
