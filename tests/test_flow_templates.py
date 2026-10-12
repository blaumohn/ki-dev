"""Rollen- und Folgetexte liegen als Vorlagen, nicht im Code."""

from __future__ import annotations

from pathlib import Path

import pytest

from ki_dev.flow import templates

STEP = Path(__file__).parent.parent / "src" / "ki_dev" / "step"


def test_missing_placeholder_value_is_an_error():
    with pytest.raises(KeyError, match="context"):
        templates.render("review", "epic-hint", id="e-1")


def test_render_fills_every_placeholder():
    text = templates.render(
        "review", "epic-hint", id="e-1", context="Ziel"
    )
    assert text == "Epic-Hinweis (e-1):\nZiel"


def test_role_texts_are_not_python_constants():
    for path in STEP.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert '"Rolle: ' not in source, path.name
        assert "Erneute Prüfung nach Korrekturen" not in source, (
            path.name
        )
