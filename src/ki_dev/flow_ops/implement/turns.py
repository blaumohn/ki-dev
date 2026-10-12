"""Eingaben an die Sitzungen des Umsetzungsablaufs, aus Vorlagen.

``implement.toml`` deklariert Vorlage und Kontext der Operationen
``work`` und ``review``; die Rollentexte stehen unter
``flow/templates/implement/``. Der Ausführer rendert sie über
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
from ki_dev.flow_ops.implement.machine import IMPLEMENT
from ki_dev.review_context import ReviewProjection
from ki_dev.runner.turns import Plug, bind_turns, render_turn

WORK = "work"
REVIEW = "review"


@dataclass(frozen=True)
class ImplementTurn:
    """Eingabe der Felder einer Übergabe des Umsetzungsablaufs."""

    task: RunTask
    round_id: int
    objection: str | None = None
    report: str = ""
    evidence: ReviewProjection | None = None
    vocabulary: ReviewVocabulary | None = None


def _vocabulary(turn: ImplementTurn) -> ReviewVocabulary:
    if turn.vocabulary is None:
        raise FlowError("Review-Übergabe braucht das Vokabular")
    return turn.vocabulary


def _criteria(turn: ImplementTurn) -> str:
    task = turn.task
    return "\n".join(
        f"- {ref}: {text}"
        for ref, text in zip(
            task.acceptance_criterion_refs(),
            task.acceptance_criteria,
            strict=True,
        )
    )


def _classes(turn: ImplementTurn) -> str:
    texts = _vocabulary(turn).texts
    return "\n".join(
        f"- {name}: {text}" for name, text in texts.items()
    )


def _evidence(turn: ImplementTurn) -> str:
    if turn.evidence is None:
        raise FlowError("Review-Übergabe braucht die Nachweise")
    return turn.evidence.text


FIELDS: dict[str, Callable[[ImplementTurn], object]] = {
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
PLUG: Plug[ImplementTurn] = Plug(FIELDS, {})
bind_turns(IMPLEMENT, PLUG, (WORK, REVIEW))


def _declared(operation: str) -> Turn:
    """Die Übergabe der Operation laut ``implement.toml``."""
    for state in IMPLEMENT.states.values():
        for candidate in state.operations:
            if candidate.do == operation and candidate.turn:
                return candidate.turn
    raise LookupError(operation)


def work_prompt(
    task: RunTask, round_id: int, objection: str | None
) -> str:
    subject = ImplementTurn(task, round_id, objection)
    turn = _declared(WORK)
    return render_turn(IMPLEMENT, turn, subject, PLUG).text()


def review_prompt(
    task: RunTask,
    round_id: int,
    report: str,
    evidence: ReviewProjection,
    vocabulary: ReviewVocabulary,
) -> str:
    subject = ImplementTurn(
        task, round_id, None, report, evidence, vocabulary
    )
    turn = _declared(REVIEW)
    return render_turn(IMPLEMENT, turn, subject, PLUG).text()
