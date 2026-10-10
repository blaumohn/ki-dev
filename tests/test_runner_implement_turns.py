"""Prompts des Umsetzungsablaufs kommen aus Vorlagen; Adapter enthalten
keine Rollentexte."""

from __future__ import annotations

from pathlib import Path

from ki_dev.adapter.contract import RunTask
from ki_dev.runner.implement_turns import work_prompt

ADAPTER = Path(__file__).parent.parent / "src" / "ki_dev" / "adapter"


def test_work_prompt_fills_the_template():
    task = RunTask(
        "run-1",
        "Auftrag",
        (),
        Path("/w"),
        "write",
        acceptance_criteria=("K",),
    )
    text = work_prompt(task, 3, None)
    assert text.startswith("Bauauftrag fuer Lauf run-1, Runde 3.\n")
    assert "Offene Beanstandung: keine\n" in text
    assert "Massgebliche Quellen:\n- keine\n" in text
    assert text.endswith("geprueft wurde.\n")


def test_adapters_carry_no_role_texts():
    for path in ADAPTER.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "Bauauftrag fuer Lauf" not in source, path.name
        assert "Unabhaengiger Review fuer Lauf" not in source, path.name
