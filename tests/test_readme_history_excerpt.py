"""Kürzung des Verlaufs für die README: Ereigniszeilen bleiben, gekürzte
Stellen sind sichtbar (tests/readme/history_excerpt.py)."""

from __future__ import annotations

from pathlib import Path

import pytest

BLOCK = [
    "Lauf x: passed nach 1 Runde",
    "  Runde 1  Umsetzer  geändert: a.py",
    "  Runde 1  Review    PASS: AC1 ist",
    "                     erfüllt, und das",
    "                     ist belegt",
    "                     fake_only: Nichts",
    "                       gefunden",
    "                     Beobachtung: offen",
    "  Abschluss          Fast-forward integriert",
    "  Offen              1 Beobachtung; vor `bd close` entscheiden",
]


@pytest.fixture
def excerpt(monkeypatch):
    monkeypatch.syspath_prepend(Path(__file__).parent / "readme")
    import history_excerpt

    return history_excerpt


def test_rows_keep_the_open_line_and_stop_after_the_history(excerpt):
    lines = ["davor", *BLOCK, "Tests green, review PASS"]
    assert excerpt.rows(lines, 1) == BLOCK


def test_compact_keeps_every_event_and_marks_the_cut(excerpt):
    assert excerpt.compact(BLOCK) == [
        "Lauf x: passed nach 1 Runde",
        "  Runde 1  Umsetzer  geändert: a.py",
        "  Runde 1  Review    PASS: AC1 ist…",
        BLOCK[-2],
        BLOCK[-1],
    ]


def test_compact_keeps_the_reason_only(excerpt):
    assert excerpt.compact(BLOCK, reasons=2)[2:5] == [
        "  Runde 1  Review    PASS: AC1 ist",
        "                     erfüllt, und das",
        "                     ist belegt…",
    ]


def test_compact_counts_findings_over_the_whole_block(excerpt):
    assert excerpt.compact(BLOCK, reasons=2, findings=2)[4:7] == [
        "                     ist belegt",
        "                     fake_only: Nichts",
        "                       gefunden…",
    ]


def test_fit_leaves_room_for_what_follows(excerpt):
    assert len(excerpt.fit(BLOCK, 6)) == 6
    assert excerpt.fit(BLOCK, 3) == excerpt.compact(BLOCK)

