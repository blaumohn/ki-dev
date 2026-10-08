"""Eingaben an Agentensitzungen der Bau- und Review-Rolle.

Der Ausführer wählt den Inhalt einer Anfrage; hier steht, wie er für
eine Agentensitzung formuliert wird. Claude, Codex und der Mensch als
Bote (der den Text in eine Sitzung trägt) erhalten denselben Wortlaut.
"""

from __future__ import annotations

from ki_dev.adapter.contract import ReviewRequest, WorkRequest


def work_prompt(request: WorkRequest) -> str:
    task = request.task
    sources = (
        "\n".join(f"- {source}" for source in task.sources) or "- keine"
    )
    criteria = "\n".join(
        f"- {ref}: {text}"
        for ref, text in zip(
            task.acceptance_criterion_refs(),
            task.acceptance_criteria,
            strict=True,
        )
    )
    objection = request.objection or "keine"
    heading = (
        f"Bauauftrag fuer Lauf {task.run_id}, Runde {request.round_id}."
    )
    return f"""{heading}
Arbeitsverzeichnis: {task.workdir}
Zugriffsprofil: {task.access_profile}
Diese Angaben beschreiben den erlaubten Lauf.
Der Prompt ist keine technische Zugriffssperre.

Gesamtauftrag:
{task.task}

Abnahmekriterien:
{criteria}

Massgebliche Quellen:
{sources}

Offene Beanstandung: {objection}
Bearbeite den Auftrag und pruefe seine Wirkung.
Arbeite innerhalb der Aufrufgrenzen. Bei fehlendem Zugriff oder
anderem Blocker beende die Arbeit mit einer konkreten Begruendung;
versuche nicht wiederholt, denselben Blocker zu umgehen.
Berichte knapp, was getan und geprueft wurde.
"""


def review_prompt(request: ReviewRequest) -> str:
    task = request.task
    sources = "\n".join(f"- {source}" for source in task.sources)
    if not sources:
        sources = "- keine"
    criteria = "\n".join(
        f"- {ref}: {text}"
        for ref, text in zip(
            task.acceptance_criterion_refs(),
            task.acceptance_criteria,
            strict=True,
        )
    )
    heading = (
        f"Unabhaengiger Review fuer Lauf {task.run_id}, "
        f"Runde {request.round_id}."
    )
    return f"""{heading}
Arbeitsverzeichnis: {task.workdir}
Zugriffsprofil: {task.access_profile}
Diese Angaben beschreiben den erlaubten Lauf.
Der Prompt ist keine technische Zugriffssperre.
Pruefe Wirkung, Tests und Quellen gegen den vollstaendigen Auftrag.
Die Projektion ist begrenzt;
behaupte bei fehlendem Nachweis keinen Vollreview.

MASSGEBLICHE QUELLEN
{sources}

BESTEHENDE ABNAHMEKRITERIEN (nur diese sind fuer CHANGES bindbar)
{criteria}

BAUBERICHT
{request.work_report.summary}

BEGRENZTE NACHWEISPROJEKTION
{request.evidence.text}

CHANGES braucht eine konkrete Bindung: welches der obigen Kriterien
ist verletzt, welches Verhalten wurde beobachtet, welcher Nachweis
belegt das. Ein Quelltext-Diff allein ist kein Ablehnungsgrund. Passt
die Beanstandung zu keinem bestehenden Kriterium oder verlangt sie
eine strengere neue Interpretation, antworte mit NEEDS_DECISION statt
CHANGES.

requirement_ref ist nur bei CHANGES gesetzt (sonst null).
Antworte ausschliesslich als JSON-Objekt mit exakt diesen Feldern:
{{"run_id":"{task.run_id}","round_id":{request.round_id},"action":"PASS|CHANGES|NEEDS_DECISION|ESCALATE","detail":"...","requirement_ref":"AC<n>|null"}}
"""
