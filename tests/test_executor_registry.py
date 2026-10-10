"""Executor-Deklarationen: Schema, Transportfähigkeiten, Gerüstdatei."""

from __future__ import annotations

import pytest

from ki_dev.adapter.executors import ExecutorSpec, Measure
from ki_dev.adapter.registry import (
    ExecutorConfigError,
    executor_specs,
    parse_executors,
)


def _declared(**executors):
    return {"executor": executors}


def test_shipped_declarations_load():
    specs = executor_specs()

    assert specs["claude"] == ExecutorSpec(
        "claude", "claude-cli", frozenset(Measure)
    )
    assert specs["codex"].measures == {Measure.QUOTA, Measure.BUDGET}
    assert specs["manual"].transport == "console"
    assert specs["inbox"].transport == "inbox"
    assert specs["mock"].measures == frozenset()


def test_measure_beyond_transport_capability_is_rejected():
    raw = _declared(
        manual={"transport": "console", "measures": ["quota"]}
    )

    with pytest.raises(
        ExecutorConfigError,
        match="executor.manual.measures: Transport console misst kein "
        "quota",
    ):
        parse_executors(raw)


def test_codex_cannot_declare_context():
    raw = _declared(
        codex={"transport": "codex-cli", "measures": ["context"]}
    )

    with pytest.raises(ExecutorConfigError, match="kein context"):
        parse_executors(raw)


def test_unknown_transport_names_known_ones():
    raw = _declared(x={"transport": "telnet", "measures": []})

    with pytest.raises(
        ExecutorConfigError, match="executor.x.transport"
    ):
        parse_executors(raw)


@pytest.mark.parametrize(
    ("item", "path"),
    [
        ({"transport": "console"}, r"executor\.manual: required"),
        (
            {"transport": "console", "measures": [], "model": "m"},
            r"executor\.manual: additionalProperties",
        ),
        (
            {"transport": "console", "measures": ["speed"]},
            r"executor\.manual\.measures\.0: enum",
        ),
        (
            {"transport": " ", "measures": []},
            r"executor\.manual\.transport: pattern",
        ),
    ],
)
def test_schema_errors_name_field_path(item, path):
    with pytest.raises(ExecutorConfigError, match=path):
        parse_executors(_declared(manual=item))
