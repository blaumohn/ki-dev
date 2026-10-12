"""Kontextgrenzen werden von der Orchestrierung durchgesetzt, nicht
vom Adapter oder einer Selbsteinschaetzung des Agenten
(ki-dev-ablauf-agu)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ki_dev.adapter.agent import (
    AgentReviewer,
    AgentWorker,
)
from ki_dev.adapter.contract import (
    RunTask,
)
from ki_dev.adapter.executors import Effort
from ki_dev.adapter.executors.contract import (
    ContextMeasurement,
    ContextStatus,
    QuotaMeasurement,
    QuotaStatus,
    TurnBudget,
    TurnResult,
    TurnStatus,
)
from ki_dev.flow_ops.implement.machine import Limits
from ki_dev.flow_ops.implement.runtime import (
    RunRuntime,
    StaticEvidenceCollector,
)
from ki_dev.repository_finalization import StaticFinalizer
from ki_dev.run_store import RunStore
from tests.executor_specs import spec_for
from tests.test_runner_runtime import _context


class ControlledExecutor:
    """Liefert einen einstellbaren Kontextmesswert und eine feste
    Turn-Antwort; misst nie selbst, ob ein Aufruf stattfinden darf."""

    def __init__(self, name: str, response: str) -> None:
        self.name = name
        self.response = response
        self.measurement = ContextMeasurement(
            ContextStatus.MEASURED, tokens=0
        )
        self.quota = QuotaMeasurement(
            QuotaStatus.MEASURED,
            used_percent=0.0,
            resets_at=9_999_999_999,
        )
        self.calls = 0
        self.context_calls = 0

    def send_turn(self, request):
        del request
        self.calls += 1
        return TurnResult(
            TurnStatus.OK,
            0,
            self.response,
            "",
            (),
            0.01,
            usage={
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cost_usd": 0.0,
            },
        )

    def measure_context(self, session_id: str) -> ContextMeasurement:
        del session_id
        self.context_calls += 1
        return self.measurement

    def measure_quota(self, session_id: str) -> QuotaMeasurement:
        del session_id
        return self.quota


def _task(run_id: str) -> RunTask:
    return RunTask(
        run_id,
        "Auftrag",
        (),
        Path("/work"),
        "write",
        acceptance_criteria=("Kriterium 1",),
    )


def _review_json(run_id: str, round_id: int, action: str) -> str:
    return json.dumps(
        {
            "run_id": run_id,
            "round_id": round_id,
            "event": action,
            "detail": "" if action == "PASS" else "Begruendung",
            "requirement_ref": None,
        }
    )


def _agents(build_executor, review_executor):
    build = AgentWorker(
        build_executor,
        "build-session",
        "model",
        Effort.LOW,
        budget=TurnBudget(),
        spec=spec_for(build_executor),
    )
    review = AgentReviewer(
        review_executor,
        "review-session",
        "model",
        Effort.LOW,
        budget=TurnBudget(),
        spec=spec_for(review_executor),
    )
    return build, review


def _runtime(tmp_path, run_id, build, review, **kwargs):
    contexts = tuple(_context(i) for i in range(1, 4))
    return RunRuntime(
        RunStore(tmp_path, run_id),
        build,
        review,
        StaticEvidenceCollector(contexts),
        StaticFinalizer(),
        **kwargs,
    )


def test_context_at_limit_blocks_call_and_writes_structured_handoff(
    tmp_path,
):
    build_executor = ControlledExecutor("claude-cli", "Bau erledigt")
    build_executor.measurement = ContextMeasurement(
        ContextStatus.MEASURED, tokens=80_000
    )
    review_executor = ControlledExecutor(
        "claude-cli", _review_json("run-ctx-limit", 1, "PASS")
    )
    build, review = _agents(build_executor, review_executor)

    with _runtime(tmp_path, "run-ctx-limit", build, review) as runtime:
        result = runtime.start(_task("run-ctx-limit"), Limits())

    assert result.status == "paused_interactive"
    assert "Kontextgrenze erreicht" in result.detail
    assert "worker" in result.detail
    assert "session=build-session" in result.detail
    assert "80000" in result.detail
    # Kein externer Aufruf und keine Budgetreservierung fuer den
    # blockierten Versuch.
    assert build_executor.calls == 0
    assert review_executor.calls == 0
    assert not (tmp_path / "run-ctx-limit" / "calls").exists()

    handoffs = list(
        (tmp_path / "run-ctx-limit" / "handoff").glob("*.json")
    )
    assert len(handoffs) == 1
    handoff = json.loads(handoffs[0].read_text())
    assert "80000" in handoff["needed_decision"]
    assert "build-session" in handoff["needed_decision"]


def test_small_context_without_other_blocker_continues_same_session(
    tmp_path,
):
    build_executor = ControlledExecutor("claude-cli", "Bau erledigt")
    build_executor.measurement = ContextMeasurement(
        ContextStatus.MEASURED, tokens=100
    )
    review_executor = ControlledExecutor(
        "claude-cli", _review_json("run-ctx-small", 1, "PASS")
    )
    review_executor.measurement = ContextMeasurement(
        ContextStatus.MEASURED, tokens=100
    )
    build, review = _agents(build_executor, review_executor)

    with _runtime(tmp_path, "run-ctx-small", build, review) as runtime:
        result = runtime.start(_task("run-ctx-small"), Limits())

    assert result.status == "passed"
    assert build_executor.calls == 1
    assert review_executor.calls == 1
    assert not list(
        (tmp_path / "run-ctx-small" / "handoff").glob("*.json")
    )


def test_small_context_with_needs_decision_still_writes_handoff(
    tmp_path,
):
    """Ein anderer Pausegrund erzeugt trotz kleinem Kontext ein
    Handoff; das erzwingt aber keinen Sitzungswechsel -- dieselbe
    Sitzung setzt nach der Antwort denselben Lauf fort."""
    run_id = "run-ctx-needs-decision"
    build_executor = ControlledExecutor("claude-cli", "Bau erledigt")
    build_executor.measurement = ContextMeasurement(
        ContextStatus.MEASURED, tokens=100
    )
    review_executor = ControlledExecutor(
        "claude-cli", _review_json(run_id, 1, "decision")
    )
    review_executor.measurement = ContextMeasurement(
        ContextStatus.MEASURED, tokens=100
    )
    build, review = _agents(build_executor, review_executor)

    with _runtime(tmp_path, run_id, build, review) as runtime:
        waiting = runtime.start(_task(run_id), Limits())
    assert waiting.status == "waiting_decision"
    handoffs = list((tmp_path / run_id / "handoff").glob("*.json"))
    assert len(handoffs) == 1

    review_executor.response = _review_json(run_id, 1, "PASS")
    with _runtime(tmp_path, run_id, build, review) as resumed:
        result = resumed.resume("Klaerung erledigt.")

    assert result.status == "passed"
    # Dieselbe Sitzung (session_id unveraendert) hat fortgesetzt.
    assert build.session_id == "build-session"
    assert review.session_id == "review-session"


def test_unavailable_measurement_blocks_and_is_not_treated_as_small(
    tmp_path,
):
    build_executor = ControlledExecutor("claude-cli", "Bau erledigt")
    build_executor.measurement = ContextMeasurement(
        ContextStatus.UNAVAILABLE,
        detail="Claude-Sitzungsverbrauch fehlt oder ist mehrdeutig",
    )
    review_executor = ControlledExecutor(
        "claude-cli", _review_json("run-ctx-unavailable", 1, "PASS")
    )
    build, review = _agents(build_executor, review_executor)

    with _runtime(
        tmp_path, "run-ctx-unavailable", build, review
    ) as runtime:
        result = runtime.start(_task("run-ctx-unavailable"), Limits())

    assert result.status == "paused_interactive"
    assert "Kontextmessung" in result.detail
    assert "fehlt" in result.detail
    assert "mehrdeutig" in result.detail
    assert build_executor.calls == 0


def test_undeclared_context_is_never_measured(tmp_path):
    """codex deklariert kein ``context``: der Wächter gilt nicht, die
    Messung wird nicht einmal angefragt."""
    build_executor = ControlledExecutor("codex-cli", "Bau erledigt")
    review_executor = ControlledExecutor(
        "codex-cli", _review_json("run-ctx-unsupported", 1, "PASS")
    )
    build, review = _agents(build_executor, review_executor)

    with _runtime(
        tmp_path, "run-ctx-unsupported", build, review
    ) as runtime:
        result = runtime.start(_task("run-ctx-unsupported"), Limits())

    assert result.status == "passed"
    assert build_executor.calls == review_executor.calls == 1
    assert build_executor.context_calls == 0
    assert review_executor.context_calls == 0


def test_declared_context_without_support_blocks(tmp_path):
    """claude deklariert ``context``: UNSUPPORTED ist kein Freibrief,
    sondern ein fehlender Pflichtwert."""
    build_executor = ControlledExecutor("claude-cli", "Bau erledigt")
    build_executor.measurement = ContextMeasurement(
        ContextStatus.UNSUPPORTED
    )
    review_executor = ControlledExecutor(
        "claude-cli", _review_json("run-ctx-declared", 1, "PASS")
    )
    build, review = _agents(build_executor, review_executor)

    with _runtime(
        tmp_path, "run-ctx-declared", build, review
    ) as runtime:
        result = runtime.start(_task("run-ctx-declared"), Limits())

    assert result.status == "paused_interactive"
    assert "Kontextmessung" in result.detail
    assert "unsupported" in result.detail
    assert build_executor.calls == 0


def test_resume_rechecks_context_instead_of_reusing_old_measurement(
    tmp_path,
):
    """Ein Sitzungswechsel/Resume darf die Grenzpruefung nicht
    stillschweigend umgehen: die naechste Runde wird erneut anhand des
    dann aktuellen Messwerts geprueft, nicht anhand des alten."""
    run_id = "run-ctx-resume-recheck"
    build_executor = ControlledExecutor("claude-cli", "Bau erledigt")
    build_executor.measurement = ContextMeasurement(
        ContextStatus.MEASURED, tokens=100
    )
    review_executor = ControlledExecutor(
        "claude-cli", _review_json(run_id, 1, "decision")
    )
    review_executor.measurement = ContextMeasurement(
        ContextStatus.MEASURED, tokens=100
    )
    build, review = _agents(build_executor, review_executor)

    with _runtime(tmp_path, run_id, build, review) as runtime:
        waiting = runtime.start(_task(run_id), Limits())
    assert waiting.status == "waiting_decision"
    assert build_executor.calls == 1
    assert review_executor.calls == 1

    # Zwischen den Runden waechst der reale Sitzungskontext der
    # Review-Rolle; die erneute Pruefung nach der Antwort muss das
    # abbilden, nicht den ersten (kleinen) Messwert weiterverwenden.
    review_executor.measurement = ContextMeasurement(
        ContextStatus.MEASURED, tokens=80_000
    )
    with _runtime(tmp_path, run_id, build, review) as resumed:
        result = resumed.resume("Klaerung erledigt.")

    assert result.status == "paused_interactive"
    assert "Kontextgrenze erreicht" in result.detail
    assert "review" in result.detail
    # Der urspruengliche Bau wird nicht wiederholt (kein neuer
    # Bauversuch), nur die Review-Rolle wird erneut geprueft.
    assert build_executor.calls == 1
    assert review_executor.calls == 1


@pytest.mark.parametrize(
    "measurement",
    [
        ContextMeasurement(ContextStatus.MEASURED, tokens=100),
        ContextMeasurement(ContextStatus.MEASURED, tokens=90_000),
        ContextMeasurement(ContextStatus.UNSUPPORTED),
        ContextMeasurement(
            ContextStatus.UNAVAILABLE, detail="Nachweis fehlt"
        ),
    ],
    ids=[
        "measured-small",
        "measured-over-limit",
        "unsupported",
        "unavailable",
    ],
)
def test_missing_role_budget_fails_loudly_regardless_of_context(
    tmp_path, measurement
):
    """xf2: ein fehlendes Rollenbudget ist keine gueltige
    Konfiguration und darf nicht stillschweigend uebergangen werden
    (Leitlinie 'Fallbacks verdecken keine Fehler') -- unabhaengig vom
    Kontextstatus, denn das Budget steuert auch Timeout und
    Verbrauchserfassung im Adapter. Rein per Mock reproduziert (kein
    echter Agenten-/CLI-Aufruf); die normale CLI-Konfiguration liefert
    immer ein TurnBudget, dieser Zustand entsteht nur durch einen
    ungueltig zusammengesetzten direkten Runtime-/Agent-Aufruf."""
    build_executor = ControlledExecutor("claude-cli", "Bau erledigt")
    build_executor.measurement = measurement
    review_executor = ControlledExecutor(
        "claude-cli", _review_json("run-ctx-no-budget", 1, "PASS")
    )
    build, review = _agents(build_executor, review_executor)
    build.budget = None

    with pytest.raises(ValueError, match="TurnBudget fehlt"), _runtime(
        tmp_path, "run-ctx-no-budget", build, review
    ) as runtime:
        runtime.start(_task("run-ctx-no-budget"), Limits())

    assert build_executor.calls == 0
