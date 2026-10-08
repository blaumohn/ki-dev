"""Das Fuenfstundenkontingent wird von der Orchestrierung durchgesetzt,
nie von einer Selbsteinschaetzung des Agenten oder einer aus
Tokenzahlen geschaetzten Naeherung (ki-dev-ablauf-hju, ueberarbeitet
in ki-dev-ablauf-dqv).

Zwei unabhaengige, gemeinsam ausgegebene Pausengruende:

- Aufgaben-Delta-Budget (``TurnBudget.
  max_usage_delta_percentage_points``, pro Rolle): wie viele
  Prozentpunkte das beobachtete, kontoweite Kontingent seit der
  Baseline dieser Rolle gewachsen ist.
- Zentrale Schutzreserve (``SafetyLimits.min_remaining_percent``):
  haelt an, sobald kaum noch Kontingent uebrig ist, unabhaengig vom
  Aufgabenbudget.

Anders als die Kontextvorpruefung (``test_context_guard.py``) gibt es
hier keinen Status, der einen Aufruf freigibt, ausser einem
tatsaechlichen Messwert: ``UNSUPPORTED`` blockiert hier ebenso wie
``UNAVAILABLE``, weil es fuer das Kontokontingent keine sichere
Annahme "kein Nachweis = ok" gibt.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from ki_dev.adapter.executors.contract import (
    QuotaMeasurement,
    QuotaStatus,
)
from ki_dev.runner.machine import Limits
from ki_dev.runner.safety import SafetyLimits
from tests.test_context_guard import (
    ControlledExecutor,
    _agents,
    _review_json,
    _runtime,
    _task,
)

FAR_FUTURE = 9_999_999_999


def _quota(used_percent: float, resets_at: int = FAR_FUTURE):
    return QuotaMeasurement(
        QuotaStatus.MEASURED,
        used_percent=used_percent,
        resets_at=resets_at,
    )


def test_delta_budget_blocks_once_role_baseline_growth_exceeds_it(
    tmp_path,
):
    run_id = "run-quota-delta"
    build_executor = ControlledExecutor("codex-cli", "Bau erledigt")
    build_executor.quota = _quota(10.0)
    review_executor = ControlledExecutor(
        "codex-cli", _review_json(run_id, 1, "decision")
    )
    review_executor.quota = _quota(10.0)
    build, review = _agents(build_executor, review_executor)
    review.budget = replace(
        review.budget, max_usage_delta_percentage_points=20.0
    )

    with _runtime(tmp_path, run_id, build, review) as runtime:
        waiting = runtime.start(_task(run_id), Limits())
    assert waiting.status == "waiting_decision"
    assert build_executor.calls == 1
    assert review_executor.calls == 1

    # Baseline der Review-Rolle liegt bei 10%; +25 Prozentpunkte
    # ueberschreitet das konfigurierte Delta-Budget von 20.
    review_executor.quota = _quota(35.0)
    with _runtime(tmp_path, run_id, build, review) as resumed:
        result = resumed.resume("Klaerung erledigt.")

    assert result.status == "paused_interactive"
    assert "Aufgaben-Delta-Budget erreicht" in result.detail
    assert "review" in result.detail
    assert "25" in result.detail
    assert "20" in result.detail
    assert build_executor.calls == 1
    assert review_executor.calls == 1


def test_low_delta_and_high_remaining_continues_same_session(
    tmp_path,
):
    build_executor = ControlledExecutor("codex-cli", "Bau erledigt")
    build_executor.quota = _quota(10.0)
    review_executor = ControlledExecutor(
        "codex-cli", _review_json("run-quota-low", 1, "PASS")
    )
    review_executor.quota = _quota(10.0)
    build, review = _agents(build_executor, review_executor)

    with _runtime(tmp_path, "run-quota-low", build, review) as runtime:
        result = runtime.start(_task("run-quota-low"), Limits())

    assert result.status == "passed"
    assert build_executor.calls == 1
    assert review_executor.calls == 1


def test_min_remaining_percent_blocks_regardless_of_delta(tmp_path):
    """Die zentrale Schutzreserve greift schon beim allerersten Aufruf
    (Delta ist dort immer 0), unabhaengig vom Aufgabenbudget."""
    build_executor = ControlledExecutor("codex-cli", "Bau erledigt")
    build_executor.quota = _quota(95.0)
    review_executor = ControlledExecutor(
        "codex-cli", _review_json("run-quota-reserve", 1, "PASS")
    )
    build, review = _agents(build_executor, review_executor)

    with _runtime(
        tmp_path,
        "run-quota-reserve",
        build,
        review,
        safety_limits=SafetyLimits(min_remaining_percent=10.0),
    ) as runtime:
        result = runtime.start(_task("run-quota-reserve"), Limits())

    assert result.status == "paused_interactive"
    assert "Schutzreserve unterschritten" in result.detail
    assert "worker" in result.detail
    assert build_executor.calls == 0
    assert review_executor.calls == 0


def test_both_blockers_are_reported_together(tmp_path):
    run_id = "run-quota-both"
    build_executor = ControlledExecutor("codex-cli", "Bau erledigt")
    build_executor.quota = _quota(50.0)
    review_executor = ControlledExecutor(
        "codex-cli", _review_json(run_id, 1, "decision")
    )
    review_executor.quota = _quota(50.0)
    build, review = _agents(build_executor, review_executor)
    review.budget = replace(
        review.budget, max_usage_delta_percentage_points=10.0
    )

    with _runtime(tmp_path, run_id, build, review) as runtime:
        waiting = runtime.start(_task(run_id), Limits())
    assert waiting.status == "waiting_decision"

    # Baseline der Review-Rolle liegt bei 50%; 92% verletzt sowohl das
    # Delta-Budget (10 Punkte) als auch die Standard-Schutzreserve
    # (verbleibend 8% <= 10%).
    review_executor.quota = _quota(92.0)
    with _runtime(tmp_path, run_id, build, review) as resumed:
        result = resumed.resume("Klaerung erledigt.")

    assert result.status == "paused_interactive"
    assert "Aufgaben-Delta-Budget erreicht" in result.detail
    assert "Schutzreserve unterschritten" in result.detail


def test_resets_at_regression_is_reported_not_crashed(tmp_path):
    """Ein resets_at, das gegenueber der gespeicherten Basislinie
    zurueckgeht, ist ein widerspruechlicher Messwert und muss als
    Pause ankommen, nicht als unbehandelter Fehler aus dem Graph-Tick
    entkommen (ki-dev-ablauf-dqv-Nachreview)."""
    run_id = "run-quota-regression"
    build_executor = ControlledExecutor("codex-cli", "Bau erledigt")
    build_executor.quota = _quota(50.0, resets_at=2000)
    review_executor = ControlledExecutor(
        "codex-cli", _review_json(run_id, 1, "decision")
    )
    review_executor.quota = _quota(50.0, resets_at=2000)
    build, review = _agents(build_executor, review_executor)

    with _runtime(tmp_path, run_id, build, review) as runtime:
        waiting = runtime.start(_task(run_id), Limits())
    assert waiting.status == "waiting_decision"

    review_executor.quota = _quota(5.0, resets_at=1000)
    with _runtime(tmp_path, run_id, build, review) as resumed:
        result = resumed.resume("Klaerung erledigt.")

    assert result.status == "paused_interactive"
    assert "widerspruechlich" in result.detail
    assert "review" in result.detail


def test_unavailable_quota_measurement_blocks_with_own_reason(
    tmp_path,
):
    build_executor = ControlledExecutor("codex-cli", "Bau erledigt")
    build_executor.quota = QuotaMeasurement(
        QuotaStatus.UNAVAILABLE,
        detail="Codex-Rollout fehlt oder ist mehrdeutig",
    )
    review_executor = ControlledExecutor(
        "codex-cli", _review_json("run-quota-unavailable", 1, "PASS")
    )
    build, review = _agents(build_executor, review_executor)

    with _runtime(
        tmp_path, "run-quota-unavailable", build, review
    ) as runtime:
        result = runtime.start(_task("run-quota-unavailable"), Limits())

    assert result.status == "paused_interactive"
    assert "Fuenfstundenkontingent-Messwert" in result.detail
    assert "fehlt" in result.detail
    assert "mehrdeutig" in result.detail
    # "Messwert fehlt" ist eine eigene Ursache, nie "Budget erschoepft".
    assert "Budget erreicht" not in result.detail
    assert build_executor.calls == 0


def test_unsupported_quota_measurement_also_blocks(tmp_path):
    """Anders als bei der Kontextvorpruefung ist ``UNSUPPORTED`` hier
    kein bekannter, unbedenklicher Adaptergrenzfall, sondern ein
    Blocker: ohne verifizierten Messweg (aktuell claude-cli) gilt der
    Echtlauf nicht als gegen das Fuenfstundenkontingent abgesichert."""
    build_executor = ControlledExecutor("claude-cli", "Bau erledigt")
    build_executor.quota = QuotaMeasurement(QuotaStatus.UNSUPPORTED)
    review_executor = ControlledExecutor(
        "claude-cli", _review_json("run-quota-unsupported", 1, "PASS")
    )
    build, review = _agents(build_executor, review_executor)

    with _runtime(
        tmp_path, "run-quota-unsupported", build, review
    ) as runtime:
        result = runtime.start(_task("run-quota-unsupported"), Limits())

    assert result.status == "paused_interactive"
    assert "Fuenfstundenkontingent-Messwert" in result.detail
    assert "unsupported" in result.detail
    assert build_executor.calls == 0


def test_quota_guard_reports_incomplete_legacy_manifest_as_blocker(
    tmp_path,
):
    """``CallLedger.limits()`` wirft ``SafetyStop`` fuer ein
    Altlauf-Manifest ohne ``min_remaining_percent``; anders als
    ``_ledger.reserve`` gibt es dafuer kein umschliessendes
    ``try/except`` in ``_progress_operation`` -- die Ausnahme darf aus
    ``_quota_guard`` deshalb nicht unbehandelt entkommen, sondern muss
    als Blocker-Text zurueckkommen (siehe Docstring von
    ``_quota_guard``)."""
    build_executor = ControlledExecutor("codex-cli", "Bau erledigt")
    review_executor = ControlledExecutor(
        "codex-cli", _review_json("run-quota-legacy", 1, "PASS")
    )
    build, review = _agents(build_executor, review_executor)

    with _runtime(
        tmp_path, "run-quota-legacy", build, review
    ) as runtime:
        runtime.store.initialize(
            {
                "safety_limits": {
                    "max_agent_calls": 6,
                    "max_total_tokens": 1_000_000,
                    "max_claude_cost_usd": 3.0,
                    "max_failed_corrections": 2,
                    "max_stagnant_changes": 3,
                }
            }
        )
        blocker = runtime._quota_guard("worker", build)

    assert blocker is not None
    assert "unvollstaendig" in blocker
    assert build_executor.calls == 0


@pytest.mark.parametrize("percent", [0.0, 99.99])
def test_safety_limits_min_remaining_percent_boundary_values_valid(
    percent,
):
    limits = SafetyLimits(min_remaining_percent=percent)
    assert limits.min_remaining_percent == percent


@pytest.mark.parametrize("percent", [-1.0, 100.0, 101.0, float("nan")])
def test_safety_limits_rejects_min_remaining_percent_outside_range(
    percent,
):
    with pytest.raises(ValueError, match="min_remaining_percent"):
        SafetyLimits(min_remaining_percent=percent)


def test_handoff_names_the_quota_pause_reason(tmp_path):
    build_executor = ControlledExecutor("codex-cli", "Bau erledigt")
    build_executor.quota = _quota(95.0)
    review_executor = ControlledExecutor(
        "codex-cli", _review_json("run-quota-handoff", 1, "PASS")
    )
    build, review = _agents(build_executor, review_executor)

    with _runtime(
        tmp_path,
        "run-quota-handoff",
        build,
        review,
        safety_limits=SafetyLimits(min_remaining_percent=10.0),
    ) as runtime:
        runtime.start(_task("run-quota-handoff"), Limits())

    handoffs = list(
        (tmp_path / "run-quota-handoff" / "handoff").glob("*.json")
    )
    assert len(handoffs) == 1
    handoff = json.loads(handoffs[0].read_text())
    assert "Schutzreserve" in handoff["needed_decision"]


def test_usage_delta_budget_is_per_role_not_shared(tmp_path):
    """Bau und Review haben unabhaengige Baselines/Budgets; ein hoher
    Verbrauch der einen Rolle blockiert die andere nicht."""
    run_id = "run-quota-per-role"
    build_executor = ControlledExecutor("codex-cli", "Bau erledigt")
    build_executor.quota = _quota(80.0)
    review_executor = ControlledExecutor(
        "codex-cli", _review_json(run_id, 1, "PASS")
    )
    review_executor.quota = _quota(5.0)
    build, review = _agents(build_executor, review_executor)
    build.budget = replace(
        build.budget, max_usage_delta_percentage_points=5.0
    )

    with _runtime(tmp_path, run_id, build, review) as runtime:
        result = runtime.start(_task(run_id), Limits())

    assert result.status == "passed"
    assert build_executor.calls == 1
    assert review_executor.calls == 1
