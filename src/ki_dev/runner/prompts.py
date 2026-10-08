"""Eingaben an die Sitzungen des Lieferablaufs, aus Vorlagen.

Die Rollentexte stehen unter ``flow/templates/delivery/``; der
Ausführer füllt sie und gibt den fertigen Prompt im Auftrag an den
Adapter. Claude, Codex und der Mensch als Bote erhalten denselben
Wortlaut; Adapter kennen weder Ablauf noch Vorlagen.
"""

from __future__ import annotations

from ki_dev.adapter.contract import ReviewVocabulary, RunTask
from ki_dev.flow.templates import render
from ki_dev.review_context import ReviewProjection

FLOW = "delivery"


def work_prompt(
    task: RunTask, round_id: int, objection: str | None
) -> str:
    # Der Prompt endet wie bisher mit einem Zeilenumbruch.
    return render(
        FLOW,
        "work",
        **_run(task, round_id),
        task=task.task,
        objection=objection or "keine",
    ) + "\n"


def review_prompt(
    task: RunTask,
    round_id: int,
    report: str,
    evidence: ReviewProjection,
    vocabulary: ReviewVocabulary,
) -> str:
    classes = "\n".join(
        f"- {name}: {text}" for name, text in vocabulary.texts.items()
    )
    return render(
        FLOW,
        "review",
        **_run(task, round_id),
        report=report,
        evidence=evidence.text,
        classes=classes,
        events="|".join(vocabulary.events),
        changes=vocabulary.changes,
        unbound=vocabulary.unbound,
    ) + "\n"


def _run(task: RunTask, round_id: int) -> dict[str, object]:
    criteria = "\n".join(
        f"- {ref}: {text}"
        for ref, text in zip(
            task.acceptance_criterion_refs(),
            task.acceptance_criteria,
            strict=True,
        )
    )
    sources = "\n".join(f"- {source}" for source in task.sources)
    return {
        "run_id": task.run_id,
        "round_id": round_id,
        "workdir": task.workdir,
        "access_profile": task.access_profile,
        "criteria": criteria,
        "sources": sources or "- keine",
    }
