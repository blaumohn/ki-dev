"""Regressionstests fuer usage_accounting.py/CallLedger-Verbrauchs-
abgleich (Nachreview zu ki-dev-ablauf-wu0.2/wu0.3).

Deckt die drei im Review konkret reproduzierten Fehler ab:
- Provider-Namensmismatch (Executor-Adaptername vs. Anbieterfamilie)
  sperrt faelschlich jede weitere Reservierung.
- Ein Summenbeleg (summary=True) laesst sich mit derselben
  Quellenreferenz zwei verschiedenen Aufrufen zuordnen und wird
  doppelt gezaehlt.
- Ergebnisnachweise ohne Startdatei (Altdaten) fielen aus dem Bericht
  komplett heraus statt als Luecke sichtbar zu bleiben.
"""

from __future__ import annotations

from dataclasses import asdict

import pytest

from ki_dev.executors.claude_cli import (
    VERIFIED_CLI_VERSION as CLAUDE_VERIFIED_CLI_VERSION,
)
from ki_dev.executors.contract import TurnResult, TurnStatus
from ki_dev.loop_safety import CallLedger, SafetyLimits, SafetyStop
from ki_dev.run_store import RunStore
from ki_dev.usage import (
    UsageStatus,
    normalize_claude_cli_result,
    normalize_codex_turn_usage,
)

# Deckungsgleich mit _codex_event()'s normalisierten Kategorien, damit
# der Legacy-Verbrauchsnachweis (finish/TurnResult.usage) und der neue
# record_usage()-Beleg nicht als widerspruechliche Summenbelege
# gegeneinander stehen (sonst summary_conflict/max() ueberdeckt die
# eigentliche Testaussage).
TURN_USAGE = {
    "input_tokens": 100,
    "output_tokens": 15,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
    "cost_usd": 0.2,
}


def _ledger(tmp_path, run_id="guard"):
    store = RunStore(tmp_path, run_id)
    store.initialize({"safety_limits": asdict(SafetyLimits())})
    return CallLedger(store)


def _finish_metered(ledger, call_id):
    result = TurnResult(
        TurnStatus.OK, 0, "ok", "", (), 1.0, usage=dict(TURN_USAGE)
    )
    ledger.finish(call_id, result, None)


def _codex_event(**overrides):
    usage = {
        "input_tokens": 100,
        "cached_input_tokens": 0,
        "output_tokens": 15,
    }
    usage.update(overrides)
    return normalize_codex_turn_usage(usage, cli_version="0.154.0")


def test_executor_name_vs_provider_family_does_not_block_next_call(
    tmp_path,
):
    """CallLedger.reserve() erhaelt den Executor-Adapternamen
    ("codex-cli"), usage.py-Normalisierer die Anbieterfamilie
    ("codex"). Ein gueltiger Beleg darf daraus keinen provider_mismatch
    erzeugen, der jede weitere Reservierung sperrt."""
    ledger = _ledger(tmp_path)
    ledger.reserve("call-1", "build", True, "codex-cli")
    ledger.record_usage(
        "call-1", _codex_event(), "evidence-1", summary=True
    )
    _finish_metered(ledger, "call-1")

    ledger.reserve("call-2", "build", True, "codex-cli")


def test_same_summary_evidence_cannot_be_charged_to_two_calls(tmp_path):
    """Dieselbe Quellenreferenz (evidence_ref) darf nicht zwei
    verschiedenen Aufrufen als Summenbeleg zugeordnet werden -- sonst
    zaehlt derselbe reale Verbrauch doppelt."""
    ledger = _ledger(tmp_path)
    event = _codex_event()

    ledger.reserve("call-1", "build", True, "codex-cli")
    ledger.record_usage("call-1", event, "same-evidence", summary=True)
    _finish_metered(ledger, "call-1")

    ledger.reserve("call-2", "build", True, "codex-cli")
    with pytest.raises(SafetyStop, match="Verbrauchsbeleg"):
        ledger.record_usage(
            "call-2", event, "same-evidence", summary=True
        )


def test_distinct_evidence_on_different_calls_is_allowed(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.reserve("call-1", "build", True, "codex-cli")
    ledger.record_usage(
        "call-1", _codex_event(), "evidence-1", summary=True
    )
    _finish_metered(ledger, "call-1")

    ledger.reserve("call-2", "build", True, "codex-cli")
    ledger.record_usage(
        "call-2", _codex_event(), "evidence-2", summary=True
    )
    _finish_metered(ledger, "call-2")

    report = ledger.usage_report()
    assert report.total == 2 * _codex_event().tokens.total


def test_claude_call_total_summary_reconciles_with_legacy_usage(
    tmp_path,
):
    """Ein aus dem echten CLI-Turnergebnis normalisierter
    UsageEvent (ki-dev-ablauf-wu0.3-Anbindung) muss mit dem
    bestehenden Legacy-Verbrauchsnachweis (finish/TurnResult.usage)
    aus demselben Turn konfliktfrei uebereinstimmen -- sonst sperrt
    ``summary_conflict``/``reconciliation_gap`` jede weitere
    Reservierung dauerhaft."""
    ledger = _ledger(tmp_path)
    event = normalize_claude_cli_result(
        TURN_USAGE,
        cli_version=CLAUDE_VERIFIED_CLI_VERSION,
        session_id="sess-1",
    )

    ledger.reserve("call-1", "build", True, "claude-cli")
    ledger.record_usage("call-1", event, "turn:call-1", summary=True)
    _finish_metered(ledger, "call-1")

    report = ledger.usage_report()
    assert len(report.calls) == 1
    call = report.calls[0]
    # Kein Einzelrequest-Beleg in diesem Ausbauschritt (ki-dev-ablauf-
    # wu0.3, AC3 bleibt offen) -- "summary_only" ist deshalb das
    # erwartete, nicht blockierende Ergebnis, nicht "matched".
    assert call.reconciliation == "summary_only"
    assert set(call.gaps) <= {"attribution_missing"}

    # Beweis, dass die Gaps tatsaechlich nicht blockieren: eine
    # weitere Reservierung bleibt moeglich.
    ledger.reserve("call-2", "build", True, "claude-cli")


def test_partial_call_total_keeps_counts_and_blocks_next_reservation(
    tmp_path,
):
    """CALL_TOTAL allein garantiert keine Freigabe: unbekannte
    Version bedeutet PARTIAL mit sichtbaren Zaehlern und Sperre.
    """
    ledger = _ledger(tmp_path)
    event = normalize_claude_cli_result(
        TURN_USAGE, cli_version="999.999.999", session_id="sess-1"
    )
    assert event.status is UsageStatus.PARTIAL
    ledger.reserve("call-1", "build", True, "claude-cli")
    _finish_metered(ledger, "call-1")
    ledger.record_usage("call-1", event, "turn:call-1", summary=True)

    report = ledger.usage_report()
    assert report.total == 115
    assert report.calls[0].counts == {
        "fresh_input": 100,
        "cache_read": 0,
        "cache_creation": 0,
        "output": 15,
    }
    assert "measurement_incomplete" in report.calls[0].gaps
    with pytest.raises(SafetyStop, match="measurement_incomplete"):
        ledger.reserve("call-2", "build", True, "claude-cli")


def test_result_without_start_file_is_visible_gap_not_dropped(tmp_path):
    """Altdaten (Ergebnis ohne Startdatei) muessen im Bericht sichtbar
    bleiben, statt aus der Summe zu verschwinden."""
    store = RunStore(tmp_path, "guard")
    store.initialize({"safety_limits": asdict(SafetyLimits())})
    (store.run_dir / "calls").mkdir(parents=True, exist_ok=True)
    store._write_once(
        store.run_dir / "calls" / "legacy-result.json",
        {
            "status": "ok",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 20,
                "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 30,
                "cost_usd": 0.2,
            },
        },
    )

    report = CallLedger(store).usage_report()

    assert report.total == 160
    assert len(report.calls) == 1
    assert "start_missing" in report.calls[0].gaps
