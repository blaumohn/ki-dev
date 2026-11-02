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

from dataclasses import asdict, replace

import pytest

from ki_dev.adapter.executors.claude_cli import (
    CLI_VERSION as CLAUDE_CLI_VERSION,
)
from ki_dev.adapter.executors.codex_cli import (
    CLI_VERSION as CODEX_CLI_VERSION,
)
from ki_dev.adapter.executors.contract import TurnResult, TurnStatus
from ki_dev.run_store import RunStore
from ki_dev.runner.safety import (
    CallLedger,
    SafetyLimits,
    SafetyStop,
)
from ki_dev.usage import (
    UsageStatus,
    normalize_claude_cli_result,
    normalize_codex_turn_usage,
)
from ki_dev.usage_accounting import UsageAttribution, UsagePurpose

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
    return normalize_codex_turn_usage(
        usage, cli_version=CODEX_CLI_VERSION
    )


def _purpose_attribution(purpose):
    return UsageAttribution(
        bead_id="ki-dev-ablauf-wu0.3.3",
        task_revision="rev-1",
        family_id="ki-dev-ablauf-wu0.3",
        family_revision="rev-1",
        role=purpose.value,
        purpose=purpose,
        session_id="sess-purpose",
    )


def _record_purpose_call(ledger, purpose, amount, *, call_id=None):
    """Ein Aufruf mit exakt ``amount`` Fresh-Input-Tokens, eindeutig
    einem der fuenf Aufwandszwecke zugerechnet. ``metered=False``
    haelt den Aufbau auf die Zweckzurechnung selbst fokussiert; er
    prueft nicht den CALL_TOTAL-Sicherungspfad fuer echte
    Agentenrollen (dafuer: test_turn_usage_integration.py)."""
    call_id = call_id or f"call-{purpose.value}"
    ledger.reserve(
        call_id,
        "worker",
        False,
        "codex-cli",
        attribution=_purpose_attribution(purpose),
    )
    event = normalize_codex_turn_usage(
        {
            "input_tokens": amount,
            "cached_input_tokens": 0,
            "output_tokens": 0,
        },
        cli_version=CODEX_CLI_VERSION,
        session_id="sess-purpose",
    )
    ledger.record_usage(
        call_id, event, f"evidence-{call_id}", summary=True
    )
    ledger.finish(call_id, None, None)


def test_executor_name_vs_provider_family_does_not_block_next_call(
    tmp_path,
):
    """CallLedger.reserve() erhaelt den Executor-Adapternamen
    ("codex-cli"), usage.py-Normalisierer die Anbieterfamilie
    ("codex"). Ein gueltiger Beleg darf daraus keinen provider_mismatch
    erzeugen, der jede weitere Reservierung sperrt."""
    ledger = _ledger(tmp_path)
    ledger.reserve("call-1", "worker", True, "codex-cli")
    ledger.record_usage(
        "call-1", _codex_event(), "evidence-1", summary=True
    )
    _finish_metered(ledger, "call-1")

    ledger.reserve("call-2", "worker", True, "codex-cli")


def test_same_summary_evidence_cannot_be_charged_to_two_calls(tmp_path):
    """Dieselbe Quellenreferenz (evidence_ref) darf nicht zwei
    verschiedenen Aufrufen als Summenbeleg zugeordnet werden -- sonst
    zaehlt derselbe reale Verbrauch doppelt."""
    ledger = _ledger(tmp_path)
    event = _codex_event()

    ledger.reserve("call-1", "worker", True, "codex-cli")
    ledger.record_usage("call-1", event, "same-evidence", summary=True)
    _finish_metered(ledger, "call-1")

    ledger.reserve("call-2", "worker", True, "codex-cli")
    with pytest.raises(SafetyStop, match="Verbrauchsbeleg"):
        ledger.record_usage(
            "call-2", event, "same-evidence", summary=True
        )


def test_distinct_evidence_on_different_calls_is_allowed(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.reserve("call-1", "worker", True, "codex-cli")
    ledger.record_usage(
        "call-1", _codex_event(), "evidence-1", summary=True
    )
    _finish_metered(ledger, "call-1")

    ledger.reserve("call-2", "worker", True, "codex-cli")
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
        cli_version=CLAUDE_CLI_VERSION,
        session_id="sess-1",
    )

    ledger.reserve("call-1", "worker", True, "claude-cli")
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
    ledger.reserve("call-2", "worker", True, "claude-cli")


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
    ledger.reserve("call-1", "worker", True, "claude-cli")
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
        ledger.reserve(
            "call-2",
            "worker",
            True,
            "claude-cli",
            limits=SafetyLimits(),
        )


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


def test_by_purpose_covers_five_effort_types_with_exact_sum(tmp_path):
    """AC3 (ki-dev-ablauf-wu0.3.3), Schritt 1: fuenf eindeutig
    gebundene Calls mit den Zwecken estimation/implementation/review/
    repair/handoff und Tokenmengen 10/20/30/40/50 ergeben in
    ``by_purpose`` genau diese fuenf Betraege und total=150."""
    ledger = _ledger(tmp_path)
    amounts = {
        UsagePurpose.ESTIMATION: 10,
        UsagePurpose.IMPLEMENTATION: 20,
        UsagePurpose.REVIEW: 30,
        UsagePurpose.REPAIR: 40,
        UsagePurpose.HANDOFF: 50,
    }
    for purpose, amount in amounts.items():
        _record_purpose_call(ledger, purpose, amount)

    report = ledger.usage_report()
    assert report.total == 150
    assert report.by_purpose == {
        "estimation": 10,
        "implementation": 20,
        "review": 30,
        "repair": 40,
        "handoff": 50,
    }


def test_unattributed_call_stays_visible_and_separate_from_purposes(
    tmp_path,
):
    """AC3, Schritt 2: ein Call ohne Attribution bleibt als
    ``unattributed`` sichtbar statt einem der fuenf Zwecke oder der
    Gesamtsumme unauffaellig zugeschlagen zu werden; die vorhandenen
    Zweckbetraege bleiben davon unberuehrt."""
    ledger = _ledger(tmp_path)
    for purpose, amount in {
        UsagePurpose.ESTIMATION: 10,
        UsagePurpose.IMPLEMENTATION: 20,
        UsagePurpose.REVIEW: 30,
        UsagePurpose.REPAIR: 40,
        UsagePurpose.HANDOFF: 50,
    }.items():
        _record_purpose_call(ledger, purpose, amount)

    ledger.reserve("call-unattributed", "worker", False, "codex-cli")
    event = normalize_codex_turn_usage(
        {
            "input_tokens": 7,
            "cached_input_tokens": 0,
            "output_tokens": 0,
        },
        cli_version=CODEX_CLI_VERSION,
        session_id="sess-purpose",
    )
    ledger.record_usage(
        "call-unattributed",
        event,
        "evidence-unattributed",
        summary=True,
    )
    ledger.finish("call-unattributed", None, None)

    report = ledger.usage_report()
    assert report.total == 157
    assert report.by_purpose == {
        "estimation": 10,
        "implementation": 20,
        "review": 30,
        "repair": 40,
        "handoff": 50,
        "unattributed": 7,
    }
    unattributed = next(
        call
        for call in report.calls
        if call.call_id == "call-unattributed"
    )
    assert "attribution_missing" in unattributed.gaps


def test_runtime_purpose_mapping_matches_round_and_role(tmp_path):
    """AC3, Schritt 3: die bestehende Laufzeit-Zuordnung
    (``runner.runtime.RunRuntime._usage_attribution``) bindet Bau-Runde
    1 an implementation, jede spaetere Bau-Runde an repair und Review
    unabhaengig von der Runde an review -- Nachweis am echten Symbol,
    nicht an einer Testnachbildung."""
    from types import SimpleNamespace

    from tests.test_runner_runtime import FakeReviewer, FakeWorker
    from tests.test_runner_safety import runtime

    with runtime(tmp_path, FakeWorker(), FakeReviewer([])) as run:
        # ``usage_task`` wird hier nur fuer diesen Test direkt ins
        # Manifest geschrieben, um die Runde/Rolle-Zuordnung isoliert
        # zu pruefen. Den echten Schreiber (start_from_config) belegt
        # tests/test_usage_task_config.py (ki-dev-ablauf-wu0.3.8).
        run.store.initialize({
            "usage_task": {
                "bead_id": "ki-dev-ablauf-wu0.3.3",
                "task_revision": "rev-1",
                "family_id": "ki-dev-ablauf-wu0.3",
                "family_revision": "rev-1",
                "parent_bead_id": "ki-dev-ablauf-wu0.3",
            }
        })
        actor = SimpleNamespace(session_id="sess-runtime")

        build_round_1 = run._usage_attribution(
            {"round_id": 1}, {"kind": "work"}, actor
        )
        build_round_2 = run._usage_attribution(
            {"round_id": 2}, {"kind": "work"}, actor
        )
        review_round_1 = run._usage_attribution(
            {"round_id": 1}, {"kind": "review"}, actor
        )
        review_round_3 = run._usage_attribution(
            {"round_id": 3}, {"kind": "review"}, actor
        )

    assert build_round_1.purpose is UsagePurpose.IMPLEMENTATION
    assert build_round_2.purpose is UsagePurpose.REPAIR
    assert review_round_1.purpose is UsagePurpose.REVIEW
    assert review_round_3.purpose is UsagePurpose.REVIEW
    assert build_round_1.bead_id == "ki-dev-ablauf-wu0.3.3"
    assert build_round_1.session_id == "sess-runtime"


def test_aborted_attempt_still_counts_under_its_purpose(tmp_path):
    """AC3: ein abgebrochener Versuch bleibt unter seinem Zweck
    sichtbar. Wie in runner.runtime._metered_operation
    wird der bekannte Teilverbrauch verbucht, bevor der Fehler das
    Ergebnis ohne Legacy-Summe abschliesst -- der Verbrauch
    verschwindet nicht mit dem gescheiterten Versuch."""
    ledger = _ledger(tmp_path)
    ledger.reserve(
        "call-aborted",
        "worker",
        True,
        "codex-cli",
        attribution=_purpose_attribution(UsagePurpose.REPAIR),
    )
    event = normalize_codex_turn_usage(
        {
            "input_tokens": 12,
            "cached_input_tokens": 0,
            "output_tokens": 0,
        },
        cli_version=CODEX_CLI_VERSION,
        session_id="sess-purpose",
    )
    ledger.record_usage(
        "call-aborted", event, "evidence-aborted", summary=True
    )
    ledger.finish(
        "call-aborted",
        TurnResult(
            TurnStatus.NONZERO_EXIT, 1, "", "abgebrochen", (), 0.0
        ),
        "Prozessfehler",
    )

    report = ledger.usage_report()
    assert report.by_purpose["repair"] == 12
    aborted = next(
        call for call in report.calls if call.call_id == "call-aborted"
    )
    assert aborted.status == "nonzero_exit"


def test_repeated_context_read_adds_to_same_purpose(tmp_path):
    """AC3: wiederholtes Kontextlesen (z. B. ein erneuter Versuch nach
    einem Protokollfehler) ist zusaetzlicher, demselben Zweck
    zugerechneter Aufwand -- kein Ersatz des vorherigen Verbrauchs."""
    ledger = _ledger(tmp_path)
    _record_purpose_call(
        ledger,
        UsagePurpose.REPAIR,
        15,
        call_id="call-repair-attempt-1",
    )
    _record_purpose_call(
        ledger,
        UsagePurpose.REPAIR,
        9,
        call_id="call-repair-attempt-2",
    )

    assert ledger.usage_report().by_purpose["repair"] == 24


def test_resubmitting_identical_evidence_for_same_call_keeps_balance(
    tmp_path,
):
    """AC3 'doppelte Beobachtung': dasselbe Ereignis fuer denselben
    Call zweimal eingereicht aendert die Bilanz nicht -- Abgrenzung
    zum unzulaessigen Fall (derselbe Beleg fuer einen ANDEREN Call,
    siehe test_same_summary_evidence_cannot_be_charged_to_two_calls)."""
    ledger = _ledger(tmp_path)
    ledger.reserve("call-1", "worker", False, "codex-cli")
    event = normalize_codex_turn_usage(
        {
            "input_tokens": 33,
            "cached_input_tokens": 0,
            "output_tokens": 0,
        },
        cli_version=CODEX_CLI_VERSION,
        session_id="sess-dup",
    )
    ledger.record_usage("call-1", event, "evidence-dup", summary=True)
    ledger.finish("call-1", None, None)
    before = ledger.usage_report()

    # Erneute Einreichung desselben Belegs fuer denselben Aufruf.
    ledger.record_usage("call-1", event, "evidence-dup", summary=True)

    after = ledger.usage_report()
    assert after == before
    assert len(ledger.store.load_usage("call-1")) == 1


def _bound_call(
    ledger, call_id, purpose, amount, *, bead_id, evidence_ref=None
):
    """Call mit expliziter UsageAttribution ueber den bestehenden
    Vertrag; kein Estimator, nur die Buchung."""
    attribution = UsageAttribution(
        bead_id=bead_id,
        task_revision="rev-1",
        family_id="ki-dev-ablauf-wu0.3",
        family_revision="rev-1",
        role=purpose.value,
        purpose=purpose,
        session_id=f"sess-{call_id}",
        parent_bead_id="ki-dev-ablauf-wu0.3",
    )
    ledger.reserve(
        call_id, "worker", False, "codex-cli", attribution=attribution
    )
    event = normalize_codex_turn_usage(
        {
            "input_tokens": amount,
            "cached_input_tokens": 0,
            "output_tokens": 0,
        },
        cli_version=CODEX_CLI_VERSION,
        session_id=f"sess-{call_id}",
    )
    ledger.record_usage(
        call_id, event, evidence_ref or f"evidence-{call_id}",
        summary=True,
    )
    ledger.finish(call_id, None, None)
    return event


def test_shared_estimation_and_handoff_count_once_in_family(tmp_path):
    """AC3, Schritt 4: gemeinsamer Schaetz-/Uebergabeaufwand wird nur
    dem Elterncall (Eltern-Bead, eigener Lauf) zugerechnet; zwei
    Kindlaeufe derselben Familie enthalten ihn nicht noch einmal.
    Die Familienauswertung weist ihn genau einmal aus."""
    parent = "ki-dev-ablauf-wu0.3"
    shared = _ledger(tmp_path, "run-shared")
    _bound_call(
        shared, "est", UsagePurpose.ESTIMATION, 10, bead_id=parent
    )
    _bound_call(
        shared, "hand", UsagePurpose.HANDOFF, 5, bead_id=parent
    )
    child_a = _ledger(tmp_path, "run-a")
    _bound_call(
        child_a, "impl-a", UsagePurpose.IMPLEMENTATION, 20,
        bead_id="ki-dev-ablauf-wu0.3.1",
    )
    child_b = _ledger(tmp_path, "run-b")
    _bound_call(
        child_b, "impl-b", UsagePurpose.IMPLEMENTATION, 30,
        bead_id="ki-dev-ablauf-wu0.3.2",
    )
    _bound_call(
        child_b, "rev-b", UsagePurpose.REVIEW, 7,
        bead_id="ki-dev-ablauf-wu0.3.2",
    )

    # Kindberichte enthalten keinen gemeinsamen Aufwand.
    assert child_a.usage_report().by_purpose == {"implementation": 20}
    assert child_b.usage_report().by_purpose == {
        "implementation": 30,
        "review": 7,
    }

    family = child_a.usage_report(family_id=parent)
    assert family.total == 10 + 5 + 20 + 30 + 7
    assert family.by_purpose == {
        "estimation": 10,
        "implementation": 50,
        "review": 7,
        "handoff": 5,
    }
    assert sorted(c.run_id for c in family.calls) == [
        "run-a", "run-b", "run-b", "run-shared", "run-shared",
    ]
    # Wiederholtes Lesen und Lesen aus anderem Lauf aendert nichts.
    assert shared.usage_report(family_id=parent) == family
    assert child_b.usage_report(family_id=parent) == family


def test_shared_effort_evidence_cannot_be_charged_to_child_call(
    tmp_path,
):
    """Derselbe Schaetzbeleg darf nicht zusaetzlich einem Kindcall
    zugerechnet werden (sonst wuerde er in der Familie vervielfacht)."""
    ledger = _ledger(tmp_path)
    event = _bound_call(
        ledger, "est", UsagePurpose.ESTIMATION, 10,
        bead_id="ki-dev-ablauf-wu0.3", evidence_ref="shared-est",
    )
    attribution = UsageAttribution(
        bead_id="ki-dev-ablauf-wu0.3.1",
        task_revision="rev-1",
        family_id="ki-dev-ablauf-wu0.3",
        family_revision="rev-1",
        role="implementation",
        purpose=UsagePurpose.IMPLEMENTATION,
        session_id="sess-child",
    )
    ledger.reserve(
        "child", "worker", False, "codex-cli", attribution=attribution
    )
    with pytest.raises(SafetyStop, match="Verbrauchsbeleg"):
        ledger.record_usage(
            "child", event, "shared-est", summary=True
        )
    assert ledger.usage_report(
        family_id="ki-dev-ablauf-wu0.3"
    ).total == 10


def _new_session_attribution():
    return replace(
        _purpose_attribution(UsagePurpose.IMPLEMENTATION),
        session_id=None,
    )


def _record_new_session_call(ledger, call_id, sessions):
    ledger.reserve(
        call_id,
        "worker",
        True,
        "codex-cli",
        attribution=_new_session_attribution(),
    )
    for number, session in enumerate(sessions):
        event = normalize_codex_turn_usage(
            {
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 15,
            },
            cli_version=CODEX_CLI_VERSION,
            session_id=session,
        )
        ledger.record_usage(
            call_id, event, f"evidence-{call_id}-{number}", summary=True
        )
    _finish_metered(ledger, call_id)


def test_call_that_creates_its_session_takes_the_id_from_its_usage(
    tmp_path,
):
    """Ohne Sitzung reserviert, mit einer Sitzung belegt: kein
    ``session_mismatch``, die Zurechnung nennt die neue Sitzung."""
    ledger = _ledger(tmp_path)
    _record_new_session_call(ledger, "call-1", ["thread-1"])

    ledger.reserve("call-2", "worker", True, "codex-cli")
    (call,) = [
        c for c in ledger.usage_report().calls if c.call_id == "call-1"
    ]
    assert "session_mismatch" not in call.gaps
    assert call.attribution.session_id == "thread-1"


def test_call_creating_a_session_with_two_ids_still_blocks(tmp_path):
    ledger = _ledger(tmp_path)
    _record_new_session_call(ledger, "call-1", ["thread-1", "thread-2"])

    with pytest.raises(SafetyStop, match="session_mismatch"):
        ledger.reserve(
            "call-2",
            "worker",
            True,
            "codex-cli",
            limits=SafetyLimits(),
        )


@pytest.mark.parametrize(
    ("status", "blocks"),
    [(TurnStatus.START_ERROR, False), (TurnStatus.NONZERO_EXIT, True)],
    ids=["nicht-gestartet", "gestartet-ohne-beleg"],
)
def test_call_without_process_has_no_unknown_effect(
    tmp_path, status, blocks
):
    """Ein Aufruf, dessen Prozess nie startete (Startfehler oder
    Ablehnung einer ungeprüften CLI-Version vor dem Turn), hat
    nachweislich nichts verbraucht und sperrt die nächste Reservierung
    nicht. Ein gestarteter Aufruf ohne Verbrauchsbeleg sperrt weiter."""
    ledger = _ledger(tmp_path)
    ledger.reserve("call-1", "worker", True, "codex-cli")
    ledger.finish(
        "call-1",
        TurnResult(status, None, "", "", (), 0.0, error="abgelehnt"),
        "AgentTurnError: abgelehnt",
    )
    gaps = set(ledger.usage_report().calls[0].gaps)
    if blocks:
        assert "external_effect_unknown" in gaps
        with pytest.raises(SafetyStop, match="unbekannt"):
            ledger.reserve(
                "call-2",
                "worker",
                True,
                "codex-cli",
                limits=SafetyLimits(),
            )
    else:
        assert gaps <= {"attribution_missing"}
        assert ledger.usage_report().total == 0
        ledger.reserve("call-2", "worker", True, "codex-cli")
