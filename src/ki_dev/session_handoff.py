"""Kompakte Uebergabe fuer eine frisch vorbereitete Rollensitzung.

Sitzungen sind aufrufergebunden vorbereitet (siehe uar.1); ki-dev
rotiert sie nicht automatisch. Bei jeder Eskalation wird stattdessen
eine kleine, auftragsgebundene Uebergabe persistiert, die ein Mensch
einer neu vorbereiteten Sitzung mitgeben kann, statt sie unbegrenzt
per Resume mit wachsendem Sitzungsverlauf fortzusetzen. Die Uebergabe
enthaelt keine Bau-/Review-Transkripte, nur bereits strukturiert
festgehaltene Review-Entscheidungen.
"""

from __future__ import annotations

from ki_dev.adapter.contract import (
    RunTask,
)
from ki_dev.ausfuehrer.run_safety import recorded_usage
from ki_dev.run_store import RunStore


def build_handoff(
    store: RunStore,
    task: RunTask,
    *,
    round_id: int,
    phase: str,
    reason: str,
) -> dict[str, object]:
    """Auftrag/Abnahme, offene und geloeste Befunde, benoetigte
    Entscheidung und bisheriger Verbrauch -- ohne Transkripte."""
    changes = [
        message
        for message in store.load_messages()
        if message.get("action") == "CHANGES"
    ]
    open_ref = changes[-1].get("requirement_ref") if changes else None
    superseded = changes[:-1]
    resolved_refs = list(
        dict.fromkeys(
            message.get("requirement_ref")
            for message in superseded
            if message.get("requirement_ref") != open_ref
        )
    )
    tokens, cost = recorded_usage(store)
    return {
        "run_id": task.run_id,
        "round_id": round_id,
        "phase": phase,
        "task": task.task,
        "acceptance_criteria": list(task.acceptance_criteria),
        "sources": list(task.sources),
        "needed_decision": reason,
        "open_requirement_ref": open_ref,
        "resolved_requirement_refs": resolved_refs,
        "discarded_attempts": [
            {
                "round_id": message.get("round_id"),
                "requirement_ref": message.get("requirement_ref"),
                "detail": message.get("detail"),
            }
            for message in superseded
        ],
        "consumed_tokens": tokens,
        "consumed_cost_usd": cost,
    }
