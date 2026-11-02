"""Messung vor der Wirkung: Kontext, Kontingent und Budgetsummen.

Messen liest Sitzungsdaten des Executors und ist deshalb eine Wirkung
(Regel 4), keine Aktion der SM. Sie läuft zwischen ``hold`` und
``start`` und kommt als Ereignis ``measured`` zurück
(:data:`~ki_dev.runner.limits.MEASUREMENT_SCHEMA`). Der Adapter misst
nur; Grenzwerte vergleicht der Wächter ``within_limits`` der SM.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import cast

from ki_dev.adapter.contract import Measurable, TurnExecutor
from ki_dev.adapter.executors.contract import (
    ContextStatus,
    Measure,
    QuotaStatus,
)
from ki_dev.run_store import RunStore, RunStoreError
from ki_dev.runner.safety import CallLedger, QuotaBaseline


class Meter:
    """Misst die Sitzung des Executors einer Rolle."""

    def __init__(
        self,
        store: RunStore,
        executors: Mapping[str | None, TurnExecutor],
    ) -> None:
        self.store = store
        self.executors = executors

    def measure(self, role: str | None) -> dict[str, object] | None:
        """Messung für ``role``; ``None``, wenn der Zustand keine Rolle
        hat (keine Agentengrenzen) oder der Executor keine Messung
        deklariert (oder fehlt: den Fehler meldet die Übergabe)."""
        executor = self.executors.get(role)
        if role is None or executor is None:
            return None
        if not executor.spec.measures:
            return None
        measures = executor.spec.measures
        session = cast(Measurable, executor)
        origin = _origin(role, executor)
        result: dict[str, object] = {"role": role}
        gaps: list[str] = []
        if Measure.CONTEXT in measures:
            result["context"] = self._context(session, origin, gaps)
        if Measure.QUOTA in measures:
            left, delta = self._quota(session, role, origin, gaps)
            result["quota_left"] = left
            result["quota_delta"] = delta
        if Measure.BUDGET in measures:
            totals = CallLedger(self.store).totals()
            gaps.extend(cast(list[str], totals.pop("gaps")))
            result.update(totals)
        result["gaps"] = gaps
        return result

    def _context(
        self, session: Measurable, origin: str, gaps: list[str]
    ) -> int | None:
        measurement = session.measure_context()
        if measurement is None:
            return None
        if measurement.status is not ContextStatus.MEASURED:
            detail = measurement.detail or measurement.status.value
            gaps.append(
                f"Kontextmessung für {origin} fehlt: {detail}; "
                "kein Aufruf ohne Nachweis"
            )
            return None
        if measurement.tokens is None:
            gaps.append(
                f"Kontextmessung für {origin} fehlt: unvollständiger "
                "Messwert; kein Aufruf ohne Nachweis"
            )
            return None
        return measurement.tokens

    def _quota(
        self,
        session: Measurable,
        role: str | None,
        origin: str,
        gaps: list[str],
    ) -> tuple[float | None, float | None]:
        measurement = session.measure_quota()
        if measurement.status is QuotaStatus.PENDING:
            return None, None
        if measurement.status is not QuotaStatus.MEASURED:
            gaps.append(quota_missing_reason(origin, measurement))
            return None, None
        if (
            measurement.used_percent is None
            or measurement.resets_at is None
        ):
            gaps.append(quota_missing_reason(origin, measurement))
            return None, None
        used = measurement.used_percent
        if (
            type(used) not in (int, float)
            or not math.isfinite(used)
            or used < 0
            or used > 100
            or type(measurement.resets_at) is not int
        ):
            gaps.append(quota_missing_reason(origin, measurement))
            return None, None
        left = min(100.0, max(0.0, 100.0 - used))
        try:
            delta = QuotaBaseline(self.store).delta_percent(
                str(role),
                used,
                cast(int, measurement.resets_at),
            )
        except RunStoreError as exc:
            gaps.append(f"Kontingent-Basislinie für {origin}: {exc}")
            return left, None
        return left, max(0.0, delta)


def quota_missing_reason(origin: str, measurement: object) -> str:
    detail = f": {measurement.detail}" if measurement.detail else ""  # type: ignore[attr-defined]
    return (
        f"Fuenfstundenkontingent-Messwert fuer {origin} fehlt "
        f"({measurement.status.value}){detail}; kein Aufruf ohne "  # type: ignore[attr-defined]
        "Nachweis"
    )


def _origin(role: str | None, executor: TurnExecutor) -> str:
    session = getattr(executor, "session_id", None) or "neu"
    return f"{role} (executor={executor.spec.name}, session={session})"
