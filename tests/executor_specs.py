"""Executor-Specs für Testdoppel: Messungen wie die Gerüstdatei."""

from __future__ import annotations

from ki_dev.adapter.executors import ExecutorSpec, Measure
from ki_dev.adapter.registry import executor_specs

# Testdoppel ohne Messung (wie manual, mock): kein Wächter, keine
# Buchung.
LOCAL = ExecutorSpec("fake", "mock", frozenset())
# Testdoppel mit gebuchtem Aufruf, ohne Kontext- und Kontingentmessung.
BOOKED = ExecutorSpec("fake", "fake", frozenset({Measure.BUDGET}))


def spec_for(executor: object) -> ExecutorSpec:
    """Spec zum Transportnamen eines (Fake-)Executors; unbekannte
    Namen buchen nur, wie ein CLI-Transport ohne Messwege."""
    name = getattr(executor, "name", "")
    for spec in executor_specs().values():
        if spec.transport == name:
            return spec
    return BOOKED
