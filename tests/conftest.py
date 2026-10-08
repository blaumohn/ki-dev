"""Gemeinsame Testumgebung."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def step_state_root(tmp_path_factory, monkeypatch):
    """Laufzustand von ``ki-dev step`` nie im Arbeitsbaum des Repos:
    jeder Test bekommt ein eigenes Verzeichnis."""
    root = tmp_path_factory.mktemp("step-state")
    monkeypatch.setattr("ki_dev.step.state.state_root", lambda: root)
    return root
