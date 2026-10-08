"""Minimale Leitlinien-Quellen für Handoff-Tests in tmp-Projekten.

Unabhängig von den echten Regeltexten: Jeder Abschnitt trägt eine
eindeutige Markierung, an der Tests die Auswahl erkennen.
"""

from __future__ import annotations

import json
from pathlib import Path

from ki_dev.step.guidelines import GUIDELINE_SOURCES

STAGES = ("map", "graph", "materialize", "implement")


def guideline_data(prefix: str) -> dict:
    """Je Schritt ein task- und ein review-Abschnitt plus common;
    ``shared`` steht mehrfach in Listen und muss einmal erscheinen."""
    ids = ["common", "shared"] + [
        f"{stage}-{kind}"
        for stage in STAGES
        for kind in ("task", "review")
    ]
    return {
        "title": f"Titel {prefix}",
        "permalink": f"/de/{prefix}/",
        "common": ["common", "shared"],
        "stages": {
            stage: {
                "task": [f"{stage}-task", "shared"],
                "review": [f"{stage}-review", "shared"],
            }
            for stage in STAGES
        },
        "sections": [
            {
                "id": section_id,
                "text": f"## {prefix} {section_id}\n\n"
                f"- {prefix}:{section_id}",
            }
            for section_id in ids
        ],
    }


def write_guidelines(root: Path) -> None:
    """Gültige Fixture-Quellen relativ zu ``root`` ablegen (JSON ist
    gültiges YAML)."""
    for index, source in enumerate(GUIDELINE_SOURCES):
        target = root / source.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(guideline_data(f"Q{index}"), ensure_ascii=False),
            encoding="utf-8",
        )
