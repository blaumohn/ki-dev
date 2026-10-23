"""Entscheidungen des Menschen in einem ``implement``-Lauf.

Ein Halt (``decision`` des Reviews, Eskalation) wartet auf den
Menschen. Er entscheidet, indem er den Auftrag im Bead ändert, und
erklärt mit ``resume --answer``, was nicht in den Bead gehört (etwa
Umgebung oder Vorgehen). ``resume`` liest den Bead neu; der geänderte
Auftrag ersetzt die Kopie im Lauf. Jede Entscheidung bleibt als
Dokument in den Laufdaten (``decisions``) und erreicht Review und
Umsetzer bis zum Ende des Laufs:

    {"round_id": 1, "answer": "Test ist veraltet",
     "criteria": [{"ref": "AC2", "old": "Test bleibt", "new": "…"}],
     "task": false, "sources": false}
"""

from __future__ import annotations

from typing import cast

from ki_dev.adapter.contract import RunTask


def decision_document(
    old: RunTask, new: RunTask, answer: str | None, round_id: int
) -> dict[str, object]:
    """Dokument einer Entscheidung: Antwort und Änderung des
    Auftrags gegenüber dem bisher geltenden Stand."""
    return {
        "round_id": round_id,
        "answer": answer,
        "criteria": _criteria_changes(old, new),
        "task": old.task != new.task,
        "sources": old.sources != new.sources,
    }


def changes_task(document: dict[str, object]) -> bool:
    """Ändert die Entscheidung den Auftrag (Bead)?"""
    return bool(
        document["criteria"] or document["task"] or document["sources"]
    )


def prompt_text(decisions: list[dict[str, object]]) -> str:
    """Abschnitt für Review und Umsetzer; ohne Entscheidung
    ``keine``."""
    if not decisions:
        return "keine"
    blocks = []
    for document in decisions:
        lines = [f"- nach Runde {document['round_id']}:"]
        for change in _criteria(document):
            ref = change["ref"]
            if change["old"] is not None:
                state = "entfaellt" if change["new"] is None else "alt"
                lines.append(f"  {ref} {state}: {change['old']}")
            if change["new"] is not None:
                lines.append(f"  {ref} neu: {change['new']}")
        if document["task"]:
            lines.append("  Auftragstext geaendert (Gesamtauftrag)")
        if document["sources"]:
            lines.append("  Quellen geaendert (siehe Quellen)")
        if document["answer"]:
            lines.append(f"  Antwort: {document['answer']}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def summary(document: dict[str, object]) -> str:
    """Eine Zeile für ``history``: was geändert wurde, dann die
    Antwort."""
    parts = [
        f"{change['ref']} geändert" for change in _criteria(document)
    ]
    if document["task"]:
        parts.append("Auftragstext geändert")
    if document["sources"]:
        parts.append("Quellen geändert")
    if document["answer"]:
        parts.append(cast(str, document["answer"]))
    return "; ".join(parts)


def _criteria_changes(
    old: RunTask, new: RunTask
) -> list[dict[str, str | None]]:
    """Je Nummer ein Eintrag, wo sich Kriterien unterscheiden; ein
    Kriterium ohne Gegenstück ist neu (``old`` null) oder entfällt
    (``new`` null)."""
    before, after = old.acceptance_criteria, new.acceptance_criteria
    changes: list[dict[str, str | None]] = []
    for index in range(max(len(before), len(after))):
        was = before[index] if index < len(before) else None
        now = after[index] if index < len(after) else None
        if was != now:
            ref = f"AC{index + 1}"
            changes.append({"ref": ref, "old": was, "new": now})
    return changes


def _criteria(
    document: dict[str, object],
) -> list[dict[str, str | None]]:
    return cast(list[dict[str, str | None]], document["criteria"])
