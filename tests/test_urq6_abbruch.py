"""Früher Abbruch der urq6-Skripte ohne lokale Quellablage.

Bezug: ki-dev-ablauf-xy78.1.1. Die Skripte nennen ihre Quellen mit
ortsunabhängiger ID; bis die Auflösung ID → Datei umgesetzt ist
(ki-dev-ablauf-xy78.2.1), enden sie vor jedem Lesen mit Exitcode 1 und
einer Meldung mit Feldpfad und Quellen-ID.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from ki_dev.pilot.quellen import QUELLABLAGE_FEHLT

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("script", "erwartet"),
    [
        (
            "scripts/urq6_test.py",
            "SESSION_9[0].path = bd:ki-dev-ablauf-phdp: ",
        ),
        (
            "scripts/urq6_prep.py",
            "SESSIONS[0][1][0].path = bd:ki-dev-ablauf-9407: ",
        ),
    ],
)
def test_urq6_bricht_ohne_quellablage_ab(script, erwartet):
    store = ROOT / "docs/architecture/urq6-run/store"
    vorher = sorted(p.name for p in store.iterdir())
    result = subprocess.run(
        [sys.executable, str(ROOT / script)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 1
    assert result.stderr.strip() == erwartet + QUELLABLAGE_FEHLT
    assert "xy78.2.1" in result.stderr and "guq" in result.stderr
    assert sorted(p.name for p in store.iterdir()) == vorher
