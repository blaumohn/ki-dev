from __future__ import annotations

from pathlib import Path

from ki_dev.loop import LoopTask
from ki_dev.run_store import RunStore
from ki_dev.session_handoff import build_handoff


def _task() -> LoopTask:
    return LoopTask(
        "run-1",
        "Auftrag",
        ("docs/vertrag.md",),
        Path("/work"),
        "write",
        acceptance_criteria=("Kriterium 1", "Kriterium 2"),
    )


def test_handoff_carries_task_and_needed_decision(tmp_path):
    store = RunStore(tmp_path, "run-1")
    handoff = build_handoff(
        store,
        _task(),
        round_id=1,
        phase="controller_step",
        reason="Sitzungskontext 90000 >= Grenze 80000",
    )
    assert handoff["task"] == "Auftrag"
    assert handoff["acceptance_criteria"] == [
        "Kriterium 1",
        "Kriterium 2",
    ]
    assert handoff["sources"] == ["docs/vertrag.md"]
    assert handoff["needed_decision"] == (
        "Sitzungskontext 90000 >= Grenze 80000"
    )
    assert handoff["open_requirement_ref"] is None
    assert handoff["resolved_requirement_refs"] == []
    assert handoff["discarded_attempts"] == []
    assert handoff["consumed_tokens"] == 0
    assert handoff["consumed_cost_usd"] == 0.0


def test_handoff_separates_resolved_from_open_reference(tmp_path):
    store = RunStore(tmp_path, "run-2")
    for round_id, ref, detail in (
        (1, "AC1", "erste Beanstandung"),
        (2, "AC2", "zweite, andere Beanstandung"),
        (3, "AC2", "AC2 bleibt verletzt"),
    ):
        store.write_message(
            f"r{round_id:04d}-review-a0000",
            {
                "run_id": "run-2",
                "round_id": round_id,
                "action": "CHANGES",
                "detail": detail,
                "requirement_ref": ref,
            },
        )

    handoff = build_handoff(
        store,
        _task(),
        round_id=3,
        phase="controller_step",
        reason="Stillstand bei AC2",
    )

    # AC1 wurde durch den Wechsel zu AC2 implizit geloest; AC2 ist
    # zum Zeitpunkt der Eskalation weiterhin offen.
    assert handoff["open_requirement_ref"] == "AC2"
    assert handoff["resolved_requirement_refs"] == ["AC1"]
    assert handoff["discarded_attempts"] == [
        {
            "round_id": 1,
            "requirement_ref": "AC1",
            "detail": "erste Beanstandung",
        },
        {
            "round_id": 2,
            "requirement_ref": "AC2",
            "detail": "zweite, andere Beanstandung",
        },
    ]


def test_handoff_contains_no_raw_transcripts(tmp_path):
    store = RunStore(tmp_path, "run-3")
    store.write_message(
        "r0001-review-a0000",
        {
            "run_id": "run-3",
            "round_id": 1,
            "action": "CHANGES",
            "detail": "Begruendung ohne Transkript",
            "requirement_ref": "AC1",
        },
    )
    handoff = build_handoff(
        store,
        _task(),
        round_id=1,
        phase="controller_step",
        reason="x",
    )
    encoded = str(handoff)
    assert "stdout" not in encoded
    assert "stderr" not in encoded
