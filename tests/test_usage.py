"""Tests fuer den Tokenmessvertrag (ki-dev-ablauf-wu0.2).

Fixtures spiegeln real beobachtete Feldnamen/-beziehungen aus lokalen
Codex-Rollouts und Claude-Sitzungstranskripten wider (Schema per
gezielter Feldnamen-/Zaehlerpruefung verifiziert, nie per Rohinhalt-
Lesen -- siehe usage.py-Moduldoc und AGENTS.md). Die konkreten Werte
in diesen Tests sind erfunden, ihre Struktur/Beziehungen nicht.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from ki_dev.executors.claude_cli import (
    CLI_VERSION as CLAUDE_CLI_VERSION,
)
from ki_dev.executors.codex_cli import (
    CLI_VERSION as CODEX_CLI_VERSION,
)
from ki_dev.usage import (
    CounterScope,
    TokenCounts,
    UsageEvent,
    UsageStatus,
    normalize_claude_cli_result,
    normalize_claude_session_message_usage,
    normalize_codex_token_count_usage,
    normalize_codex_turn_usage,
    read_claude_session_usage,
    read_codex_rollout_usage,
    read_jsonl_lenient,
)


class TestTokenCounts:
    def test_total_sums_all_four_categories(self):
        counts = TokenCounts(
            fresh_input=10, cache_read=5, cache_creation=3, output=20
        )
        assert counts.total == 38

    def test_reasoning_output_may_equal_output(self):
        TokenCounts(
            fresh_input=1,
            cache_read=0,
            cache_creation=0,
            output=10,
            reasoning_output=10,
        )

    def test_reasoning_output_beyond_output_rejected(self):
        with pytest.raises(ValueError, match="reasoning_output"):
            TokenCounts(
                fresh_input=1,
                cache_read=0,
                cache_creation=0,
                output=10,
                reasoning_output=11,
            )

    def test_negative_category_rejected(self):
        with pytest.raises(ValueError):
            TokenCounts(
                fresh_input=-1, cache_read=0, cache_creation=0, output=0
            )

    def test_ephemeral_sub_categories_must_sum_to_cache_creation(self):
        TokenCounts(
            fresh_input=0,
            cache_read=0,
            cache_creation=12,
            output=0,
            cache_creation_ephemeral_5m=7,
            cache_creation_ephemeral_1h=5,
        )
        with pytest.raises(ValueError, match="ephemere"):
            TokenCounts(
                fresh_input=0,
                cache_read=0,
                cache_creation=12,
                output=0,
                cache_creation_ephemeral_5m=7,
                cache_creation_ephemeral_1h=6,
            )

    def test_ephemeral_sub_categories_only_together(self):
        with pytest.raises(ValueError, match="gemeinsam"):
            TokenCounts(
                fresh_input=0,
                cache_read=0,
                cache_creation=7,
                output=0,
                cache_creation_ephemeral_5m=7,
            )


class TestUsageEvent:
    def test_measured_requires_tokens(self):
        with pytest.raises(ValueError, match="tokens"):
            UsageEvent(
                UsageStatus.MEASURED,
                "claude",
                "cli_result",
                CounterScope.PER_REQUEST,
            )

    def test_unavailable_forbids_tokens(self):
        tokens = TokenCounts(0, 0, 0, 0)
        with pytest.raises(ValueError, match="tokens"):
            UsageEvent(
                UsageStatus.UNAVAILABLE,
                "claude",
                "cli_result",
                CounterScope.PER_REQUEST,
                tokens=tokens,
            )

    def test_empty_provider_rejected(self):
        with pytest.raises(ValueError, match="provider"):
            UsageEvent(
                UsageStatus.UNAVAILABLE,
                "",
                "cli_result",
                CounterScope.PER_REQUEST,
            )


class TestClaudeCliResult:
    """Flacher Vertrag von ``claude -p --output-format json``, das
    "result"-Ereignis (siehe executors/metering.py:_claude_usage)."""

    def _usage(self, **overrides):
        value = {
            "input_tokens": 10,
            "output_tokens": 20,
            "cache_read_input_tokens": 500,
            "cache_creation_input_tokens": 30,
        }
        value.update(overrides)
        return value

    def test_valid_usage_is_measured(self):
        event = normalize_claude_cli_result(
            self._usage(),
            cli_version=CLAUDE_CLI_VERSION,
            session_id="s1",
        )
        assert event.status is UsageStatus.MEASURED
        assert event.provider == "claude"
        assert event.source == "cli_result"
        # Ein CLI-Aufruf kann intern mehrere Modell-Requests umfassen
        # (Werkzeugnutzung); das result-Ereignis ist deren Summe.
        assert event.counter_scope is CounterScope.CALL_TOTAL
        assert event.tokens == TokenCounts(10, 500, 30, 20)
        assert event.cli_version == CLAUDE_CLI_VERSION
        assert event.session_id == "s1"

    def test_missing_cli_version_is_partial_not_measured(self):
        event = normalize_claude_cli_result(self._usage())
        assert event.status is UsageStatus.PARTIAL
        assert event.tokens == TokenCounts(10, 500, 30, 20)
        assert "cli_version" in event.detail

    def test_missing_usage_is_unavailable(self):
        event = normalize_claude_cli_result(None)
        assert event.status is UsageStatus.UNAVAILABLE
        assert event.tokens is None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"input_tokens": None},
            {"output_tokens": -1},
            {"cache_read_input_tokens": "500"},
        ],
    )
    def test_invalid_field_is_unavailable(self, overrides):
        event = normalize_claude_cli_result(self._usage(**overrides))
        assert event.status is UsageStatus.UNAVAILABLE
        assert event.detail


class TestClaudeSessionMessageUsage:
    """Reichhaltiger Vertrag aus dem interaktiven Sitzungstranskript
    (``message.usage``), empirisch an echten lokalen Sitzungsdateien
    verifiziert: ``cache_creation`` und ``output_tokens_details`` sind
    optionale Unterkategorien, keine Pflichtfelder."""

    def _usage(self, **overrides):
        value = {
            "input_tokens": 4,
            "output_tokens": 50,
            "cache_read_input_tokens": 1000,
            "cache_creation_input_tokens": 12,
            "cache_creation": {
                "ephemeral_5m_input_tokens": 7,
                "ephemeral_1h_input_tokens": 5,
            },
            "output_tokens_details": {"thinking_tokens": 30},
            "service_tier": "standard",
        }
        value.update(overrides)
        return value

    def test_rich_usage_is_measured_with_subcategories(self):
        event = normalize_claude_session_message_usage(
            self._usage(),
            schema_version=CLAUDE_CLI_VERSION,
            confirmed_model="claude-haiku-4-5-20251001",
        )
        assert event.status is UsageStatus.MEASURED
        assert event.tokens.reasoning_output == 30
        assert event.tokens.cache_creation_ephemeral_5m == 7
        assert event.tokens.cache_creation_ephemeral_1h == 5
        assert event.confirmed_model == "claude-haiku-4-5-20251001"

    def test_usage_without_subcategories_is_still_measured(self):
        usage = self._usage()
        del usage["cache_creation"]
        del usage["output_tokens_details"]
        event = normalize_claude_session_message_usage(
            usage, schema_version=CLAUDE_CLI_VERSION
        )
        assert event.status is UsageStatus.MEASURED
        assert event.tokens.reasoning_output is None
        assert event.tokens.cache_creation_ephemeral_5m is None

    def test_missing_schema_version_is_partial_not_measured(self):
        event = normalize_claude_session_message_usage(self._usage())
        assert event.status is UsageStatus.PARTIAL
        assert event.tokens.reasoning_output == 30
        assert "schema_version" in event.detail

    def test_inconsistent_ephemeral_split_is_partial_not_dropped(self):
        usage = self._usage(
            cache_creation={
                "ephemeral_5m_input_tokens": 7,
                "ephemeral_1h_input_tokens": 999,
            }
        )
        event = normalize_claude_session_message_usage(
            usage, schema_version=CLAUDE_CLI_VERSION
        )
        assert event.status is UsageStatus.PARTIAL
        # Hauptkategorien bleiben erhalten, nur die widerspruechliche
        # Unterkategorie wird nicht uebernommen.
        assert event.tokens.fresh_input == 4
        assert event.tokens.reasoning_output is None
        assert "widerspruechlich" in event.detail


class TestCodexTurnUsage:
    """``codex exec --json``, ``turn.completed``-Ereignis (siehe
    executors/metering.py:codex_result). ``input_tokens`` ist
    inklusive Cache -- empirisch an echten Rollouts bestaetigt."""

    def test_valid_usage_subtracts_cache_from_input(self):
        event = normalize_codex_turn_usage(
            {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 15,
            },
            cli_version=CODEX_CLI_VERSION,
        )
        assert event.status is UsageStatus.MEASURED
        # Ein Turn kann intern mehrere Modell-Requests umfassen
        # (Werkzeugnutzung); turn.completed ist deren Summe.
        assert event.counter_scope is CounterScope.CALL_TOTAL
        assert event.tokens.fresh_input == 60
        assert event.tokens.cache_read == 40
        assert event.tokens.output == 15

    def test_missing_cli_version_is_partial_not_measured(self):
        event = normalize_codex_turn_usage(
            {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 15,
            }
        )
        assert event.status is UsageStatus.PARTIAL
        assert event.tokens.fresh_input == 60

    def test_cache_greater_than_input_is_unavailable(self):
        event = normalize_codex_turn_usage(
            {
                "input_tokens": 10,
                "cached_input_tokens": 40,
                "output_tokens": 15,
            }
        )
        assert event.status is UsageStatus.UNAVAILABLE


class TestCodexTokenCountUsage:
    """``payload.info.last_token_usage``/``total_token_usage`` aus der
    lokalen Rollout-Datei (siehe executors/metering.py:codex_quota).
    Empirisch bestaetigt: ``total_tokens == input_tokens +
    output_tokens`` (Reasoning bereits in output enthalten)."""

    def test_consistent_usage_is_measured(self):
        event = normalize_codex_token_count_usage(
            {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 15,
                "reasoning_output_tokens": 3,
                "total_tokens": 115,
            },
            scope=CounterScope.PER_REQUEST,
            cli_version=CODEX_CLI_VERSION,
        )
        assert event.status is UsageStatus.MEASURED
        assert event.source == "rollout_last_token_usage"
        assert event.tokens.fresh_input == 60
        assert event.tokens.reasoning_output == 3

    def test_missing_cli_version_is_partial_not_measured(self):
        event = normalize_codex_token_count_usage(
            {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 15,
                "total_tokens": 115,
            },
            scope=CounterScope.PER_REQUEST,
        )
        assert event.status is UsageStatus.PARTIAL
        assert "cli_version" in event.detail

    def test_reasoning_greater_than_output_is_partial_not_raised(self):
        """Ein widerspruechlicher reasoning_output_tokens-Wert darf die
        Normalisierung nicht mit ValueError abbrechen (P1-Befund);
        die Hauptkategorien bleiben trotzdem erhalten."""
        event = normalize_codex_token_count_usage(
            {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 15,
                "reasoning_output_tokens": 999,
                "total_tokens": 75,
            },
            scope=CounterScope.PER_REQUEST,
            cli_version=CODEX_CLI_VERSION,
        )
        assert event.status is UsageStatus.PARTIAL
        assert event.tokens.fresh_input == 60
        assert event.tokens.reasoning_output is None
        assert "reasoning_output_tokens" in event.detail

    def test_present_but_invalid_total_is_not_silently_ignored(self):
        """Ein vorhandenes, aber typwidriges total_tokens darf nicht wie
        ein fehlendes Feld behandelt werden (P1-Befund): beides fuehrt
        sonst zu MEASURED, obwohl die Quelle intern widerspruechlich
        ist."""
        event = normalize_codex_token_count_usage(
            {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 15,
                "total_tokens": "not-a-number",
            },
            scope=CounterScope.PER_REQUEST,
            cli_version=CODEX_CLI_VERSION,
        )
        assert event.status is UsageStatus.PARTIAL
        assert event.tokens.fresh_input == 60
        assert "total_tokens" in event.detail

    def test_cumulative_scope_uses_total_source_name(self):
        event = normalize_codex_token_count_usage(
            {
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 15,
                "total_tokens": 115,
            },
            scope=CounterScope.CUMULATIVE_SESSION,
        )
        assert event.source == "rollout_total_token_usage"

    def test_total_mismatch_from_compaction_anomaly_is_partial(self):
        """Real beobachtete Anomalie: last_token_usage meldet nach
        einem Kontextereignis alle Einzelwerte als 0, waehrend
        total_tokens noch eine alte Summe traegt. Die Nullen werden
        nicht stillschweigend als gemessen durchgereicht."""
        event = normalize_codex_token_count_usage(
            {
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "reasoning_output_tokens": 0,
                "total_tokens": 35754,
            },
            scope=CounterScope.PER_REQUEST,
        )
        assert event.status is UsageStatus.PARTIAL
        assert event.tokens.total == 0
        assert "35754" in event.detail

    def test_missing_info_usage_is_unavailable(self):
        event = normalize_codex_token_count_usage(
            None, scope=CounterScope.PER_REQUEST
        )
        assert event.status is UsageStatus.UNAVAILABLE


class TestReadJsonlLenient:
    """wu0.2-Akzeptanzkriterium 3: unvollstaendige letzte Zeile wird
    spaeter erneut gelesen, kaputte innere Zeilen werden sichtbar,
    Mehrfachlesen ist idempotent (zustandsloser Vollscan)."""

    def test_complete_file_reads_all_rows(self, tmp_path):
        path = tmp_path / "data.jsonl"
        path.write_text('{"a": 1}\n{"a": 2}\n')
        result = read_jsonl_lenient(path)
        assert result.rows == ({"a": 1}, {"a": 2})
        assert result.corrupt_lines == ()
        assert result.incomplete_last_line is False

    def test_incomplete_last_line_is_excluded_not_corrupt(
        self, tmp_path
    ):
        path = tmp_path / "data.jsonl"
        path.write_text('{"a": 1}\n{"a": 2, "b"')
        result = read_jsonl_lenient(path)
        assert result.rows == ({"a": 1},)
        assert result.corrupt_lines == ()
        assert result.incomplete_last_line is True

    def test_reread_after_completion_picks_up_the_line(self, tmp_path):
        path = tmp_path / "data.jsonl"
        path.write_text('{"a": 1}\n{"a": 2, "b"')
        assert read_jsonl_lenient(path).rows == ({"a": 1},)
        with path.open("a") as handle:
            handle.write(': 3}\n')
        result = read_jsonl_lenient(path)
        assert result.rows == ({"a": 1}, {"a": 2, "b": 3})
        assert result.incomplete_last_line is False

    def test_corrupt_inner_line_is_visible_and_does_not_abort(
        self, tmp_path
    ):
        path = tmp_path / "data.jsonl"
        path.write_text('{"a": 1}\nnot json\n{"a": 3}\n')
        result = read_jsonl_lenient(path)
        assert result.rows == ({"a": 1}, {"a": 3})
        assert result.corrupt_lines == (2,)

    def test_non_object_line_is_corrupt(self, tmp_path):
        path = tmp_path / "data.jsonl"
        path.write_text('[1, 2]\n{"a": 1}\n')
        result = read_jsonl_lenient(path)
        assert result.rows == ({"a": 1},)
        assert result.corrupt_lines == (1,)

    def test_repeated_reads_are_idempotent(self, tmp_path):
        path = tmp_path / "data.jsonl"
        path.write_text('{"a": 1}\nnot json\n{"a": 3}')
        first = read_jsonl_lenient(path)
        second = read_jsonl_lenient(path)
        assert first == second


def _rollout_line(**kwargs):
    row = {
        "type": "event_msg",
        "timestamp": "2026-04-04T09:00:00.000Z",
        "payload": {"type": "token_count", "info": {}},
    }
    row.update(kwargs)
    return json.dumps(row)


class TestReadCodexRolloutUsage:
    """Reale Rollout-Struktur (empirisch verifiziert, siehe
    usage.py-Moduldoc): mehrere last_token_usage-Ereignisse pro
    Request, total_token_usage kumulativ ueber die Sitzung."""

    def _info(self, **overrides):
        value = {
            "last_token_usage": {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 15,
                "total_tokens": 115,
            },
            "total_token_usage": {
                "input_tokens": 300,
                "cached_input_tokens": 40,
                "output_tokens": 45,
                "total_tokens": 345,
            },
        }
        value.update(overrides)
        return value

    def test_extracts_per_request_and_latest_cumulative_event(
        self, tmp_path
    ):
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            _rollout_line(
                timestamp="2026-04-04T09:00:00.000Z",
                payload={
                    "type": "token_count",
                    "info": self._info(),
                },
            )
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        cumulative = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.CUMULATIVE_SESSION
        ]
        assert len(per_request) == 1
        assert per_request[0].tokens.fresh_input == 60
        assert len(cumulative) == 1
        assert cumulative[0].tokens.fresh_input == 260

    def test_unsorted_events_keep_latest_cumulative_by_time(
        self, tmp_path
    ):
        """Zeilenreihenfolge ist keine Zeitreihenfolge (siehe
        executors/metering.py:_latest_five_hour_window): die zeitlich
        juengere Zeile steht hier zuerst in der Datei."""
        newer = self._info(
            total_token_usage={
                "input_tokens": 900,
                "cached_input_tokens": 0,
                "output_tokens": 90,
                "total_tokens": 990,
            }
        )
        older = self._info()
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            _rollout_line(
                timestamp="2026-04-04T10:00:00.000Z",
                payload={"type": "token_count", "info": newer},
            )
            + "\n"
            + _rollout_line(
                timestamp="2026-04-04T09:00:00.000Z",
                payload={"type": "token_count", "info": older},
            )
            + "\n"
        )
        scan = read_codex_rollout_usage(path)
        cumulative = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.CUMULATIVE_SESSION
        ]
        assert len(cumulative) == 1
        assert cumulative[0].tokens.fresh_input == 900

    def test_non_token_count_lines_are_ignored(self, tmp_path):
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            json.dumps({"type": "session_meta", "payload": {}}) + "\n"
        )
        scan = read_codex_rollout_usage(path)
        assert scan.events == ()

    def test_corrupt_and_incomplete_lines_are_surfaced(self, tmp_path):
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            "not json\n"
            + _rollout_line(payload={"type": "token_count", "info": {}})
            + "\n{incomplete"
        )
        scan = read_codex_rollout_usage(path)
        assert scan.corrupt_lines == (1,)
        assert scan.incomplete_last_line is True


def _assistant_row(**kwargs):
    row = {
        "type": "assistant",
        "sessionId": "sess-1",
        "requestId": "req-1",
        "version": CLAUDE_CLI_VERSION,
        "timestamp": "2026-04-04T09:00:00.000Z",
        "message": {
            "id": "msg-1",
            "model": "claude-haiku-4-5-20251001",
            "usage": {
                "input_tokens": 4,
                "output_tokens": 50,
                "cache_read_input_tokens": 1000,
                "cache_creation_input_tokens": 12,
            },
        },
    }
    row.update(kwargs)
    return json.dumps(row)


class TestReadClaudeSessionUsage:
    """Streaming kann dieselbe Modellantwort ueber mehrere Zeilen mit
    identischer message.id aufteilen (siehe
    scripts/analyze_claude_usage.py); nur die letzte Zeile zaehlt."""

    def test_streaming_duplicates_are_deduplicated_by_message_id(
        self, tmp_path
    ):
        path = tmp_path / "session.jsonl"
        path.write_text(
            _assistant_row()
            + "\n"
            + _assistant_row(
                message={
                    "id": "msg-1",
                    "model": "claude-haiku-4-5-20251001",
                    "usage": {
                        "input_tokens": 4,
                        "output_tokens": 999,
                        "cache_read_input_tokens": 1000,
                        "cache_creation_input_tokens": 12,
                    },
                }
            )
            + "\n"
        )
        scan = read_claude_session_usage(path)
        assert len(scan.events) == 1
        assert scan.events[0].tokens.output == 999

    def test_synthetic_model_is_skipped(self, tmp_path):
        path = tmp_path / "session.jsonl"
        path.write_text(
            _assistant_row(
                message={
                    "id": "msg-2",
                    "model": "<synthetic>",
                    "usage": {"input_tokens": 0},
                }
            )
            + "\n"
        )
        scan = read_claude_session_usage(path)
        assert scan.events == ()

    def test_row_fields_are_threaded_into_the_event(self, tmp_path):
        path = tmp_path / "session.jsonl"
        path.write_text(_assistant_row() + "\n")
        scan = read_claude_session_usage(path)
        assert len(scan.events) == 1
        event = scan.events[0]
        assert event.session_id == "sess-1"
        assert event.request_id == "req-1"
        assert event.schema_version == CLAUDE_CLI_VERSION
        assert event.confirmed_model == "claude-haiku-4-5-20251001"
        assert event.status is UsageStatus.MEASURED

    def test_missing_message_id_is_kept_not_dropped(self, tmp_path):
        path = tmp_path / "session.jsonl"
        path.write_text(
            _assistant_row(
                message={
                    "model": "claude-haiku-4-5-20251001",
                    "usage": {
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                }
            )
            + "\n"
        )
        scan = read_claude_session_usage(path)
        assert len(scan.events) == 1

    def test_non_string_version_field_does_not_crash_the_reader(
        self, tmp_path
    ):
        """[P2] Eine reale Zeile mit "version": 123 (Zahl statt
        String) darf den Reader nicht mit einem ungefangenen
        TypeError abbrechen."""
        path = tmp_path / "session.jsonl"
        path.write_text(_assistant_row(version=123) + "\n")
        scan = read_claude_session_usage(path)
        assert len(scan.events) == 1
        assert scan.events[0].status is UsageStatus.PARTIAL


class TestNachreviewDf44275:
    """Regressionstests zu den sechs Befunden aus dem Nachreview von
    df44275 (siehe Beads ki-dev-ablauf-wu0.2, zweiter Nachreview)."""

    def test_diagnostic_text_is_bounded_not_raw_content(self):
        """[P1] Ein beliebig langer Fremdwert darf nie unbegrenzt in
        detail landen (Sentinel-Leak/Ausgabegrenze)."""
        sentinel = "S" * 10_000
        event = normalize_codex_token_count_usage(
            {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 15,
                "total_tokens": sentinel,
            },
            scope=CounterScope.PER_REQUEST,
            cli_version=CODEX_CLI_VERSION,
        )
        assert event.status is UsageStatus.PARTIAL
        assert len(event.detail) < 200
        assert sentinel not in event.detail

    def _paired_info(self, total_tokens, **last_overrides):
        last = {
            "input_tokens": 100,
            "cached_input_tokens": 40,
            "output_tokens": 15,
            "total_tokens": 115,
        }
        last.update(last_overrides)
        # total_token_usage muss dieselbe Kategorienaufteilung wie
        # last_token_usage decken (kumulative Summe enthaelt jeden
        # Request je Kategorie, nicht nur in der Gesamtsumme) --
        # sonst kein realistischer Beleg (siehe wu0.2-Nachreview
        # 2c69ddc, Finding [P2] Zeile 934).
        factor = total_tokens // last["total_tokens"]
        return {
            "last_token_usage": last,
            "total_token_usage": {
                "input_tokens": last["input_tokens"] * factor,
                "cached_input_tokens": (
                    last["cached_input_tokens"] * factor
                ),
                "output_tokens": last["output_tokens"] * factor,
                "total_tokens": total_tokens,
            },
        }

    def test_unchanged_cumulative_means_no_new_request(self, tmp_path):
        """[P2] Der urspruengliche Befund blieb bei blossem Zeit-/
        Inhaltsvergleich bestehen: gleiche Zaehler, unterschiedliche
        Zeitpunkte, aber UNVERAENDERTER kumulativer Zaehler -> kein
        neuer realer Request (empirisch an echten Rollouts bestaetigt,
        siehe usage.py-Moduldoc: identischer last_token_usage-Inhalt
        ging nie mit gewachsenem total_token_usage einher)."""
        path = tmp_path / "rollout.jsonl"
        first = _rollout_line(
            timestamp="2026-04-04T09:00:00.000Z",
            payload={
                "type": "token_count",
                "info": self._paired_info(115),
            },
        )
        second = _rollout_line(
            timestamp="2026-04-04T09:05:00.000Z",
            payload={
                "type": "token_count",
                "info": self._paired_info(115),
            },
        )
        path.write_text(first + "\n" + second + "\n")
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert len(per_request) == 1
        assert per_request[0].tokens.total == 115
        cumulative = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.CUMULATIVE_SESSION
        ]
        assert cumulative[0].tokens.total == 115

    def test_grown_cumulative_counts_both_requests_even_if_equal_cost(
        self, tmp_path
    ):
        """[P2] Umkehrprobe: waechst der kumulative Zaehler zwischen
        zwei Ereignissen, handelt es sich um echte, getrennte Requests
        -- auch wenn ihr last_token_usage zufaellig gleich hoch ist.
        Ein reiner Inhaltsvergleich wuerde das faelschlich verwerfen
        (empirisch: 13 von 315 echten last_token_usage-Ereignissen
        wiederholten den Vorgaengerwert, aber der kumulative Zaehler
        blieb dabei immer unveraendert -- kein Gegenbeispiel mit
        Wachstum gefunden)."""
        path = tmp_path / "rollout.jsonl"
        first = _rollout_line(
            timestamp="2026-04-04T09:00:00.000Z",
            payload={
                "type": "token_count",
                "info": self._paired_info(115),
            },
        )
        second = _rollout_line(
            timestamp="2026-04-04T09:05:00.000Z",
            payload={
                "type": "token_count",
                "info": self._paired_info(230),
            },
        )
        path.write_text(first + "\n" + second + "\n")
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert len(per_request) == 2

    def test_cumulative_decrease_is_flagged_not_silent(self, tmp_path):
        """[P2] Ein Rueckgang eines kumulativen Snapshots gegenueber
        einem frueheren in derselben Datei (z. B. 115 -> 11) muss
        sichtbar bleiben, nicht als unveraendert gueltig gemessen
        gelten."""
        earlier = _rollout_line(
            timestamp="2026-04-04T09:00:00.000Z",
            payload={
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 0,
                        "output_tokens": 15,
                        "total_tokens": 115,
                    }
                },
            },
        )
        later = _rollout_line(
            timestamp="2026-04-04T09:05:00.000Z",
            payload={
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 10,
                        "cached_input_tokens": 0,
                        "output_tokens": 1,
                        "total_tokens": 11,
                    }
                },
            },
        )
        path = tmp_path / "rollout.jsonl"
        path.write_text(earlier + "\n" + later + "\n")
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        cumulative = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.CUMULATIVE_SESSION
        ]
        assert len(cumulative) == 1
        assert cumulative[0].tokens.total == 11
        assert cumulative[0].status is UsageStatus.PARTIAL
        assert "gesunken" in cumulative[0].detail

    def test_reset_stays_flagged_even_after_later_recovery(
        self, tmp_path
    ):
        """[P2] Die Folge 115 -> 11 -> 130 muss auch dann als Reset
        erkannt werden, wenn der Zaehler danach wieder ueber den
        urspruenglichen Wert waechst -- ein Vergleich nur gegen den
        letzten Wert (statt gegen die gesamte geordnete Folge) haette
        130 > 115 als unauffaellig durchgehen lassen."""

        def line(ts, total):
            return _rollout_line(
                timestamp=ts,
                payload={
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": total,
                            "cached_input_tokens": 0,
                            "output_tokens": 0,
                            "total_tokens": total,
                        }
                    },
                },
            )

        path = tmp_path / "rollout.jsonl"
        path.write_text(
            line("2026-04-04T09:00:00.000Z", 115)
            + "\n"
            + line("2026-04-04T09:05:00.000Z", 11)
            + "\n"
            + line("2026-04-04T09:10:00.000Z", 130)
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        cumulative = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.CUMULATIVE_SESSION
        ]
        assert len(cumulative) == 1
        assert cumulative[0].tokens.total == 130
        assert cumulative[0].status is UsageStatus.PARTIAL
        assert "gesunken" in cumulative[0].detail

    def test_session_meta_id_and_cli_version_are_used(self, tmp_path):
        """[P2] session_meta traegt Sitzungskennung und CLI-Version;
        sie duerfen nicht verworfen werden, sonst scheitert die
        kumulative Zuordnung im Accounting an
        counter_baseline_unknown."""
        path = tmp_path / "rollout.jsonl"
        meta = json.dumps(
            {
                "type": "session_meta",
                "timestamp": "2026-04-04T08:59:00.000Z",
                "payload": {
                    "id": "sess-abc",
                    "cli_version": CODEX_CLI_VERSION,
                },
            }
        )
        usage_line = _rollout_line(
            timestamp="2026-04-04T09:00:00.000Z",
            payload={
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 40,
                        "output_tokens": 15,
                        "total_tokens": 115,
                    },
                    # Eigener kumulativer Beleg macht dieses Ereignis
                    # direkt bestaetigt; dieser Test prueft session_id/
                    # cli_version-Uebernahme, nicht Bestaetigungsstatus.
                    "total_token_usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 40,
                        "output_tokens": 15,
                        "total_tokens": 115,
                    },
                },
            },
        )
        path.write_text(meta + "\n" + usage_line + "\n")
        scan = read_codex_rollout_usage(path)
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert len(per_request) == 1
        event = per_request[0]
        assert event.session_id == "sess-abc"
        assert event.cli_version == CODEX_CLI_VERSION
        assert event.status is UsageStatus.MEASURED

    def test_truncated_multibyte_tail_does_not_abort_the_scan(
        self, tmp_path
    ):
        """[P2] Ein aktiver Schreibvorgang kann mitten in einem
        Mehrbyte-UTF-8-Zeichen enden; bereits vollstaendige Zeilen
        muessen trotzdem lesbar bleiben, kein UnicodeDecodeError."""
        path = tmp_path / "data.jsonl"
        complete = json.dumps({"a": 1, "note": "ä"}).encode("utf-8")
        truncated_multibyte = "ö".encode()[:1]
        with path.open("wb") as handle:
            handle.write(complete + b"\n")
            handle.write(b'{"a": 2, "note": "' + truncated_multibyte)
        result = read_jsonl_lenient(path)
        assert result.rows == ({"a": 1, "note": "ä"},)
        assert result.incomplete_last_line is True
        assert result.corrupt_lines == ()

    def test_unrecognized_version_string_is_partial_not_measured(self):
        """[P2] Ein beliebiger nichtleerer String (z. B. ein Tippfehler)
        ist kein gueltiger Versionsnachweis."""
        event = normalize_codex_turn_usage(
            {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 15,
            },
            cli_version="unrecognized-version",
        )
        assert event.status is UsageStatus.PARTIAL
        assert "unterstuetzte Version" in event.detail
        assert "unrecognized-version" not in event.detail

    def test_well_formed_but_unsupported_version_is_partial(self):
        """[P2] Ein plausibel geformter, aber nicht lokal verifizierter
        Versionswert (z. B. eine erfundene zukuenftige Version) ist
        kein implizit gueltiger Messwert -- ein Formatmuster allein
        reicht nicht."""
        event = normalize_codex_turn_usage(
            {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 15,
            },
            cli_version="999.999.999",
        )
        assert event.status is UsageStatus.PARTIAL
        assert "unterstuetzte Version" in event.detail

    def test_non_string_version_does_not_crash(self):
        """[P2] Ein JSON-Zahlenwert statt eines Strings (z. B.
        "version": 123 in einer Sitzungszeile) darf keinen
        ungefangenen TypeError verursachen."""
        event = normalize_codex_turn_usage(
            {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 15,
            },
            cli_version=123,  # type: ignore[arg-type]
        )
        assert event.status is UsageStatus.PARTIAL


class TestNachreview3ac1ebe:
    """Regressionstests zu den drei Befunden aus dem Nachreview von
    3ac1ebe (siehe Beads ki-dev-ablauf-wu0.2, vierter Nachreview)."""

    def test_requests_recognized_again_after_reset(self, tmp_path):
        """[P2] Nach einem Rueckgang (115 -> 0) muss ein neuer Request
        oberhalb des NEUEN, niedrigeren Standes wieder erkannt werden
        (115 -> 0 -> 11): die Vergleichsbasis darf nicht am
        historischen Hoechststand haengen bleiben."""

        def line(ts, total, last_output=None):
            info = {
                "total_token_usage": {
                    "input_tokens": total,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": total,
                }
            }
            if last_output is not None:
                info["last_token_usage"] = {
                    "input_tokens": last_output,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": last_output,
                }
            return _rollout_line(
                timestamp=ts,
                payload={"type": "token_count", "info": info},
            )

        path = tmp_path / "rollout.jsonl"
        path.write_text(
            line("2026-04-04T09:00:00.000Z", 115, last_output=115)
            + "\n"
            + line("2026-04-04T09:05:00.000Z", 0)
            + "\n"
            + line("2026-04-04T09:10:00.000Z", 11, last_output=11)
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert [e.tokens.total for e in per_request] == [115, 11]
        cumulative = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.CUMULATIVE_SESSION
        ]
        assert cumulative[0].status is UsageStatus.PARTIAL
        assert "gesunken" in cumulative[0].detail

    def test_duplicate_without_cumulative_evidence_not_double_counted(
        self, tmp_path
    ):
        """[P2] Ohne jeden kumulativen Beleg (kein total_token_usage
        ueberhaupt) ist Inhaltsgleichheit mit der unmittelbar
        vorangegangenen Zeile das einzige verfuegbare Duplikatsignal
        -- zwei identische last_token_usage-Zeilen ohne total_token_
        usage duerfen nicht als zwei Requests gezaehlt werden."""
        info = {
            "last_token_usage": {
                "input_tokens": 100,
                "cached_input_tokens": 40,
                "output_tokens": 15,
                "total_tokens": 115,
            },
        }
        path = tmp_path / "rollout.jsonl"
        line = _rollout_line(
            timestamp="2026-04-04T09:00:00.000Z",
            payload={"type": "token_count", "info": info},
        )
        other_time_line = _rollout_line(
            timestamp="2026-04-04T09:05:00.000Z",
            payload={"type": "token_count", "info": info},
        )
        path.write_text(line + "\n" + other_time_line + "\n")
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert len(per_request) == 1
        assert per_request[0].tokens.total == 115

    def test_distinct_content_without_cumulative_both_count(
        self, tmp_path
    ):
        """Gegenprobe: unterscheidet sich der Inhalt, zaehlen beide
        Requests, auch ohne kumulativen Beleg."""

        def line(ts, total):
            return _rollout_line(
                timestamp=ts,
                payload={
                    "type": "token_count",
                    "info": {
                        "last_token_usage": {
                            "input_tokens": total,
                            "cached_input_tokens": 0,
                            "output_tokens": 0,
                            "total_tokens": total,
                        }
                    },
                },
            )

        path = tmp_path / "rollout.jsonl"
        path.write_text(
            line("2026-04-04T09:00:00.000Z", 100)
            + "\n"
            + line("2026-04-04T09:05:00.000Z", 200)
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert len(per_request) == 2

    def test_invalid_latest_summary_is_not_replaced_by_older_valid_one(
        self, tmp_path
    ):
        """[P2] Folgt auf eine gueltige Summe eine typwidrige (der
        Schluessel total_token_usage ist z. B. ein String statt eines
        Objekts), muss diese ungueltige, juengste Beobachtung sichtbar
        bleiben -- nicht stillschweigend durch die aeltere gueltige
        Summe ersetzt werden."""
        valid = _rollout_line(
            timestamp="2026-04-04T09:00:00.000Z",
            payload={
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 0,
                        "output_tokens": 15,
                        "total_tokens": 115,
                    }
                },
            },
        )
        invalid = _rollout_line(
            timestamp="2026-04-04T09:05:00.000Z",
            payload={
                "type": "token_count",
                "info": {"total_token_usage": "kaputt"},
            },
        )
        path = tmp_path / "rollout.jsonl"
        path.write_text(valid + "\n" + invalid + "\n")
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        cumulative = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.CUMULATIVE_SESSION
        ]
        assert len(cumulative) == 1
        assert cumulative[0].status is UsageStatus.UNAVAILABLE


class TestNachreviewAf4cf95:
    """Regressionstests zu den zwei Befunden aus dem Nachreview von
    af4cf95 (siehe Beads ki-dev-ablauf-wu0.2, fuenfter Nachreview)."""

    def test_missing_then_confirmed_summary_merges_not_doubles(
        self, tmp_path
    ):
        """[P2] Summe 115/Request 115, dann Summe fehlt/Request 11,
        dann Summe 126/Request erneut 11: die dritte Zeile bestaetigt
        per eigenem kumulativem Beleg (126 = 115 + 11) dieselbe
        Beobachtung wie die zweite -- das darf nicht als dritter,
        zusaetzlicher Request gezaehlt werden (115 + 11, nicht 137)."""

        def line(ts, total=None, last=None):
            info = {}
            if total is not None:
                info["total_token_usage"] = {
                    "input_tokens": total,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": total,
                }
            if last is not None:
                info["last_token_usage"] = {
                    "input_tokens": last,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": last,
                }
            return _rollout_line(
                timestamp=ts,
                payload={"type": "token_count", "info": info},
            )

        path = tmp_path / "rollout.jsonl"
        path.write_text(
            line("2026-04-04T09:00:00.000Z", total=115, last=115)
            + "\n"
            + line("2026-04-04T09:05:00.000Z", last=11)
            + "\n"
            + line("2026-04-04T09:10:00.000Z", total=126, last=11)
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert [e.tokens.total for e in per_request] == [115, 11]
        assert per_request[1].status is UsageStatus.MEASURED
        cumulative = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.CUMULATIVE_SESSION
        ]
        assert cumulative[0].tokens.total == 126

    def test_own_summary_after_reset_is_kept_as_separate_request(
        self, tmp_path
    ):
        """[P2] Summen 115 -> 11 -> 22 mit je eigenem Requestwert 115,
        11, 11: jedes Ereignis traegt seinen EIGENEN kumulativen Beleg
        (auch der Reset auf 11 selbst), beide Requests nach dem ersten
        muessen erhalten bleiben -- nicht nur "115, 11", sondern
        "115, 11, 11" (137 gesamt)."""

        def line(ts, total, last):
            return _rollout_line(
                timestamp=ts,
                payload={
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {
                            "input_tokens": total,
                            "cached_input_tokens": 0,
                            "output_tokens": 0,
                            "total_tokens": total,
                        },
                        "last_token_usage": {
                            "input_tokens": last,
                            "cached_input_tokens": 0,
                            "output_tokens": 0,
                            "total_tokens": last,
                        },
                    },
                },
            )

        path = tmp_path / "rollout.jsonl"
        path.write_text(
            line("2026-04-04T09:00:00.000Z", 115, 115)
            + "\n"
            + line("2026-04-04T09:05:00.000Z", 11, 11)
            + "\n"
            + line("2026-04-04T09:10:00.000Z", 22, 11)
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert [e.tokens.total for e in per_request] == [115, 11, 11]
        assert all(
            e.status is UsageStatus.MEASURED for e in per_request
        )

    def test_unconfirmed_pending_at_end_of_file_is_partial(
        self, tmp_path
    ):
        """Gegenprobe: bleibt ein last_token_usage bis Dateiende ohne
        jeden kumulativen Beleg, wird es als PARTIAL abgeschlossen,
        nicht verworfen und nicht als MEASURED behauptet."""
        info = {
            "last_token_usage": {
                "input_tokens": 100,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 100,
            }
        }
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            _rollout_line(
                timestamp="2026-04-04T09:00:00.000Z",
                payload={"type": "token_count", "info": info},
            )
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        assert len(scan.events) == 1
        assert scan.events[0].status is UsageStatus.PARTIAL
        assert scan.events[0].tokens.total == 100


class TestNachreview7431ea6:
    """Regressionstests zu den drei Befunden aus dem Nachreview von
    7431ea6 (siehe Beads ki-dev-ablauf-wu0.2, sechster Nachreview)."""

    def _line(self, ts, total=None, last=None):
        info = {}
        if total is not None:
            info["total_token_usage"] = {
                "input_tokens": total,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": total,
            }
        if last is not None:
            info["last_token_usage"] = {
                "input_tokens": last,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": last,
            }
        return _rollout_line(
            timestamp=ts, payload={"type": "token_count", "info": info}
        )

    def test_growth_covering_both_keeps_both_equal_requests(
        self, tmp_path
    ):
        """[P2] (115,115) -> (fehlt,11) -> (137,11): der Zuwachs von
        22 deckt zwei 11er-Anfragen ab, nicht nur eine -- beide
        muessen erhalten bleiben (137 gesamt, nicht 126)."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            self._line("2026-04-04T09:00:00.000Z", total=115, last=115)
            + "\n"
            + self._line("2026-04-04T09:05:00.000Z", last=11)
            + "\n"
            + self._line("2026-04-04T09:10:00.000Z", total=137, last=11)
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert [e.tokens.total for e in per_request] == [115, 11, 11]
        assert all(
            e.status is UsageStatus.MEASURED for e in per_request
        )

    def test_growth_covering_only_one_still_merges(self, tmp_path):
        """Gegenprobe (unveraendert aus dem fuenften Nachreview):
        (115,115) -> (fehlt,11) -> (126,11) -- der Zuwachs von 11
        deckt nur eine Anfrage ab, beide Beobachtungen sind dieselbe
        (126 gesamt, nicht 137)."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            self._line("2026-04-04T09:00:00.000Z", total=115, last=115)
            + "\n"
            + self._line("2026-04-04T09:05:00.000Z", last=11)
            + "\n"
            + self._line("2026-04-04T09:10:00.000Z", total=126, last=11)
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert [e.tokens.total for e in per_request] == [115, 11]

    def test_unchanged_summary_resolves_open_pending(self, tmp_path):
        """[P2] (115,115) -> (fehlt,115) -> (115,115): der dritte
        Beleg zeigt unveraendertes Wachstum und widerlegt damit das
        offene Pending -- nur ein Request, keine zusaetzliche PARTIAL-
        Verdopplung derselben Beobachtung."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            self._line("2026-04-04T09:00:00.000Z", total=115, last=115)
            + "\n"
            + self._line("2026-04-04T09:05:00.000Z", last=115)
            + "\n"
            + self._line(
                "2026-04-04T09:10:00.000Z", total=115, last=115
            )
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert len(per_request) == 1
        assert per_request[0].tokens.total == 115

    def test_unordered_without_summary_is_partial(self, tmp_path):
        """[P2] Ein last_token_usage ohne Zeitstempel UND ohne
        kumulativen Beleg muss genauso unbestaetigt (PARTIAL) bleiben
        wie im zeitlich geordneten Pfad."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {
                                "input_tokens": 100,
                                "cached_input_tokens": 0,
                                "output_tokens": 0,
                                "total_tokens": 100,
                            }
                        },
                    },
                }
            )
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        assert len(scan.events) == 1
        assert scan.events[0].status is UsageStatus.PARTIAL
        assert scan.events[0].tokens.total == 100

    def test_unordered_with_own_summary_is_measured(self, tmp_path):
        """Gegenprobe: traegt ein zeitlich nicht einordenbares
        Ereignis seinen eigenen, gueltigen kumulativen Beleg, ist es
        in sich abgeschlossen bestaetigt (MEASURED)."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {
                                "input_tokens": 100,
                                "cached_input_tokens": 0,
                                "output_tokens": 0,
                                "total_tokens": 100,
                            },
                            "total_token_usage": {
                                "input_tokens": 100,
                                "cached_input_tokens": 0,
                                "output_tokens": 0,
                                "total_tokens": 100,
                            },
                        },
                    },
                }
            )
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert len(per_request) == 1
        assert per_request[0].status is UsageStatus.MEASURED


class TestNachreview19b6e88:
    """Regressionstests zu den drei Befunden aus dem Nachreview von
    19b6e88 (siehe Beads ki-dev-ablauf-wu0.2, siebter Nachreview)."""

    def _line(self, ts, total=None, last=None):
        info = {}
        if total is not None:
            info["total_token_usage"] = {
                "input_tokens": total,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": total,
            }
        if last is not None:
            info["last_token_usage"] = {
                "input_tokens": last,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": last,
            }
        return _rollout_line(
            timestamp=ts, payload={"type": "token_count", "info": info}
        )

    def test_missing_baseline_does_not_confirm_duplicate(
        self, tmp_path
    ):
        """[P2] (fehlend,11) -> (11,11): ohne vorherigen Zaehlerstand
        ist der Zuwachs unbekannt, aber schon die absolute Summe (11)
        schliesst "zwei 11er-Anfragen" (bräuchte 22) aus -- bei
        identischem Inhalt bleibt nur "derselbe Vorgang" uebrig.
        Erwartet: genau eine MEASURED-Anfrage, keine PARTIAL-
        Verdopplung."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            self._line("2026-04-04T09:00:00.000Z", last=11)
            + "\n"
            + self._line("2026-04-04T09:05:00.000Z", total=11, last=11)
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert len(per_request) == 1
        assert per_request[0].status is UsageStatus.MEASURED
        assert per_request[0].tokens.total == 11

    def test_missing_baseline_with_ambiguous_total_stays_partial(
        self, tmp_path
    ):
        """Gegenprobe: (fehlend,11) -> (30,11) -- die absolute Summe
        (30) ist gross genug, dass "zwei 11er-Anfragen" (22) rechnerisch
        nicht ausgeschlossen ist, aber auch nicht belegt (30 != 22).
        Die Zuordnung bleibt ungeklaert -- das Pending muss als
        PARTIAL sichtbar bleiben statt MEASURED bestaetigt zu werden."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            self._line("2026-04-04T09:00:00.000Z", last=11)
            + "\n"
            + self._line("2026-04-04T09:05:00.000Z", total=30, last=11)
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert [e.tokens.total for e in per_request] == [11, 11]
        assert [e.status for e in per_request] == [
            UsageStatus.PARTIAL,
            UsageStatus.MEASURED,
        ]

    def test_insufficient_growth_does_not_confirm_duplicate(
        self, tmp_path
    ):
        """[P2] (115,115) -> (fehlt,11) -> (120,11): der Zuwachs von 5
        deckt weder eine noch zwei 11er-Anfragen -- die Zuordnung ist
        ungeklaert, das Pending darf nicht als zweite MEASURED-Anfrage
        bestaetigt werden."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            self._line("2026-04-04T09:00:00.000Z", total=115, last=115)
            + "\n"
            + self._line("2026-04-04T09:05:00.000Z", last=11)
            + "\n"
            + self._line("2026-04-04T09:10:00.000Z", total=120, last=11)
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        measured_elevens = [
            e
            for e in per_request
            if e.status is UsageStatus.MEASURED and e.tokens.total == 11
        ]
        # Folgerunde: der Zuwachs (5) deckt nicht einmal den eigenen
        # Requestwert (11) -- widerspruechlicher Beleg, also gar keine
        # MEASURED-Bestaetigung; die Wiederholung zaehlt nicht doppelt.
        assert measured_elevens == []
        assert [e.tokens.total for e in per_request] == [115, 11]
        assert per_request[1].status is UsageStatus.PARTIAL

    def test_unchanged_summary_keeps_differing_pending_visible(
        self, tmp_path
    ):
        """[P2] (115,115) -> (fehlt,11) -> (115,115): die unveraenderte
        Summe belegt nur, dass sich der Zaehler nicht veraendert hat --
        nicht, dass der abweichende 11er-Pending-Wert dieselbe
        Beobachtung wie der 115er-Request ist. Der 11er-Wert muss
        sichtbar bleiben (als unbestaetigt), nicht verschwinden."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            self._line("2026-04-04T09:00:00.000Z", total=115, last=115)
            + "\n"
            + self._line("2026-04-04T09:05:00.000Z", last=11)
            + "\n"
            + self._line(
                "2026-04-04T09:10:00.000Z", total=115, last=115
            )
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert [e.tokens.total for e in per_request] == [115, 11]
        assert per_request[0].status is UsageStatus.MEASURED
        assert per_request[1].status is UsageStatus.PARTIAL

    def test_unordered_summary_without_individual_counters_is_partial(
        self, tmp_path
    ):
        """[P2] Ein unordered total_token_usage, das nur total_tokens
        traegt (keine der erforderlichen Einzelzaehler input_tokens/
        cached_input_tokens/output_tokens), ist kein eigenstaendiger
        Beleg -- er muss denselben Validierungsvertrag erfuellen wie
        jede andere normalisierte Summe und darf last_token_usage
        nicht stillschweigend zu MEASURED befoerdern."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {
                                "input_tokens": 100,
                                "cached_input_tokens": 0,
                                "output_tokens": 0,
                                "total_tokens": 100,
                            },
                            "total_token_usage": {
                                "total_tokens": 100,
                            },
                        },
                    },
                }
            )
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert len(per_request) == 1
        assert per_request[0].status is UsageStatus.PARTIAL

    def test_unordered_summary_with_inconsistent_total_is_not_own_beleg(
        self, tmp_path
    ):
        """Ein unordered total_token_usage mit gueltigen Einzelzaehlern,
        aber einem intern widersprechenden total_tokens (ungueltiger
        Typ), erfuellt denselben Vertrag wie jede andere normalisierte
        Summe nicht (dort PARTIAL statt MEASURED) und darf deshalb
        genauso wenig als eigenstaendiger Beleg zaehlen wie ein ganz
        fehlender total_tokens-Wert."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": {
                                "input_tokens": 100,
                                "cached_input_tokens": 0,
                                "output_tokens": 0,
                                "total_tokens": 100,
                            },
                            "total_token_usage": {
                                "input_tokens": 5,
                                "cached_input_tokens": 0,
                                "output_tokens": 5,
                                "total_tokens": "abc",
                            },
                        },
                    },
                }
            )
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert len(per_request) == 1
        assert per_request[0].status is UsageStatus.PARTIAL

    def test_unchanged_summary_tracks_new_differing_value_as_pending(
        self, tmp_path
    ):
        """[Nachreview-Folgefund] (115,115) -> (fehlt,11) -> (115,99):
        beim dritten Ereignis ist die Summe unveraendert, aber last=99
        passt weder zum offenen Pending (11) noch zum zuletzt
        bestaetigten Inhalt (115) -- es ist eine dritte, eigenstaendig
        unbelegte Beobachtung und muss selbst sichtbar bleiben (als
        neues Pending), statt beim Verwerfen des alten Pendings
        ebenfalls zu verschwinden."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            self._line("2026-04-04T09:00:00.000Z", total=115, last=115)
            + "\n"
            + self._line("2026-04-04T09:05:00.000Z", last=11)
            + "\n"
            + self._line("2026-04-04T09:10:00.000Z", total=115, last=99)
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert [e.tokens.total for e in per_request] == [115, 11, 99]
        assert [e.status for e in per_request] == [
            UsageStatus.MEASURED,
            UsageStatus.PARTIAL,
            UsageStatus.PARTIAL,
        ]

    def test_unchanged_summary_merge_does_not_recreate_pending(
        self, tmp_path
    ):
        """(115,115) -> (200,85) -> (fehlt,115) -> (200,115): das
        vierte Ereignis wiederholt das offene, noch nicht ausgegebene
        Pending (115) -- es wird damit zusammengefuehrt (kein zweites
        Pending, keine Doppelzaehlung), bleibt aber als genau eine
        unbestaetigte Beobachtung sichtbar. Der laengst ueberholte
        Inhalt aus Ereignis 1 (Zaehlerstand 115, nicht mehr 200) darf
        es weder bestaetigen noch unterdruecken."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            self._line(
                "2026-04-04T09:00:00.000Z", total=115, last=115
            )
            + "\n"
            + self._line(
                "2026-04-04T09:05:00.000Z", total=200, last=85
            )
            + "\n"
            + self._line("2026-04-04T09:10:00.000Z", last=115)
            + "\n"
            + self._line(
                "2026-04-04T09:15:00.000Z", total=200, last=115
            )
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert [e.tokens.total for e in per_request] == [115, 85, 115]
        assert [e.status for e in per_request] == [
            UsageStatus.MEASURED,
            UsageStatus.MEASURED,
            UsageStatus.PARTIAL,
        ]

    def test_unchanged_summary_stale_content_match_stays_visible(
        self, tmp_path
    ):
        """(115,115) -> (200,85) -> (200,115): die dritte Beobachtung
        hat denselben Inhalt wie die laengst ueberholte erste (bei
        Zaehlerstand 115), nicht wie die aktuell gueltige zweite (bei
        Zaehlerstand 200) -- die Uebereinstimmung ist zufaellig und
        darf die neue Beobachtung nicht stillschweigend
        unterdruecken."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            self._line(
                "2026-04-04T09:00:00.000Z", total=115, last=115
            )
            + "\n"
            + self._line(
                "2026-04-04T09:05:00.000Z", total=200, last=85
            )
            + "\n"
            + self._line(
                "2026-04-04T09:10:00.000Z", total=200, last=115
            )
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert [e.tokens.total for e in per_request] == [115, 85, 115]
        assert [e.status for e in per_request] == [
            UsageStatus.MEASURED,
            UsageStatus.MEASURED,
            UsageStatus.PARTIAL,
        ]


class TestNachreview19b6e88Folgerunde:
    """Regressionstests zu den drei Befunden aus der Pruefung des
    Arbeitsbaums nach dem Nachreview von 19b6e88 (siehe Beads
    ki-dev-ablauf-wu0.2, siebter Nachreview)."""

    _line = TestNachreview19b6e88._line

    def _per_request(self, tmp_path, *lines):
        path = tmp_path / "rollout.jsonl"
        path.write_text("".join(line + "\n" for line in lines))
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        return scan, [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]

    def test_repeated_unconfirmed_value_stays_visible(self, tmp_path):
        """[P2] (115,115) -> (115,11) -> (115,11): die Wiederholung
        wird mit dem noch nicht ausgegebenen Pending zusammengefuehrt,
        loescht es aber nicht -- genau ein 11er bleibt als PARTIAL
        sichtbar."""
        _, per_request = self._per_request(
            tmp_path,
            self._line("2026-04-04T09:00:00.000Z", total=115, last=115),
            self._line("2026-04-04T09:05:00.000Z", total=115, last=11),
            self._line("2026-04-04T09:10:00.000Z", total=115, last=11),
        )
        assert [e.tokens.total for e in per_request] == [115, 11]
        assert [e.status for e in per_request] == [
            UsageStatus.MEASURED,
            UsageStatus.PARTIAL,
        ]

    def test_repeated_confirmed_value_still_merges(self, tmp_path):
        """Gegenprobe (Vertrag des sechsten Nachreviews):
        (115,115) -> (fehlt,115) -> (115,115) bleibt genau ein
        MEASURED-Eintrag -- die Wiederholung passt zum bei genau
        diesem Zaehlerstand bestaetigten Inhalt."""
        _, per_request = self._per_request(
            tmp_path,
            self._line("2026-04-04T09:00:00.000Z", total=115, last=115),
            self._line("2026-04-04T09:05:00.000Z", last=115),
            self._line("2026-04-04T09:10:00.000Z", total=115, last=115),
        )
        assert [e.tokens.total for e in per_request] == [115]
        assert per_request[0].status is UsageStatus.MEASURED

    def test_pure_summary_growth_invalidates_confirmed_content(
        self, tmp_path
    ):
        """[P2] (115,115) -> (200,fehlt) -> (200,115): der bei Stand
        115 bestaetigte Inhalt gilt bei Stand 200 nicht mehr als
        bereits ausgegeben -- die letzte Beobachtung bleibt als
        unbestaetigt sichtbar statt unterdrueckt zu werden."""
        _, per_request = self._per_request(
            tmp_path,
            self._line("2026-04-04T09:00:00.000Z", total=115, last=115),
            self._line("2026-04-04T09:05:00.000Z", total=200),
            self._line("2026-04-04T09:10:00.000Z", total=200, last=115),
        )
        assert [e.tokens.total for e in per_request] == [115, 115]
        assert [e.status for e in per_request] == [
            UsageStatus.MEASURED,
            UsageStatus.PARTIAL,
        ]

    def test_summary_below_request_value_is_not_confirmation(
        self, tmp_path
    ):
        """[P2] (fehlt,11) -> (5,11): eine Summe kleiner als der
        eigene Requestwert widerspricht sich selbst -- kein Request
        darf MEASURED sein, der Widerspruch ist per Diagnose sichtbar
        und die inhaltsgleiche Wiederholung zaehlt nicht doppelt."""
        _, per_request = self._per_request(
            tmp_path,
            self._line("2026-04-04T09:00:00.000Z", last=11),
            self._line("2026-04-04T09:05:00.000Z", total=5, last=11),
        )
        assert [e.tokens.total for e in per_request] == [11]
        assert per_request[0].status is UsageStatus.PARTIAL
        assert "kleiner" in per_request[0].detail

    def test_summary_below_request_value_after_baseline(self, tmp_path):
        """Derselbe Widerspruch mit vorhandener Vergleichsbasis
        (Rueckgang auf 5 bei Request 11): ebenfalls keine
        Bestaetigung; ein abweichendes offenes Pending bleibt
        eigenstaendig unbestaetigt."""
        _, per_request = self._per_request(
            tmp_path,
            self._line("2026-04-04T09:00:00.000Z", total=115, last=115),
            self._line("2026-04-04T09:05:00.000Z", last=7),
            self._line("2026-04-04T09:10:00.000Z", total=5, last=11),
        )
        assert [e.tokens.total for e in per_request] == [115, 7, 11]
        assert [e.status for e in per_request] == [
            UsageStatus.MEASURED,
            UsageStatus.PARTIAL,
            UsageStatus.PARTIAL,
        ]

    def test_reset_to_exact_request_value_still_confirms(
        self, tmp_path
    ):
        """Gegenprobe: (115,115) -> (11,11) -- nach einem Reset deckt
        die neue Summe den Request genau; das bleibt eine direkte
        Bestaetigung."""
        _, per_request = self._per_request(
            tmp_path,
            self._line("2026-04-04T09:00:00.000Z", total=115, last=115),
            self._line("2026-04-04T09:05:00.000Z", total=11, last=11),
        )
        assert [e.tokens.total for e in per_request] == [115, 11]
        assert all(
            e.status is UsageStatus.MEASURED for e in per_request
        )

    def test_growth_below_request_value_is_not_confirmation(
        self, tmp_path
    ):
        """Dieselbe Invariante bei vorhandener Vergleichsbasis:
        (115,115) -> (120,11) -- der Zuwachs 5 deckt den Request 11
        nicht; kein MEASURED fuer den 11er."""
        _, per_request = self._per_request(
            tmp_path,
            self._line("2026-04-04T09:00:00.000Z", total=115, last=115),
            self._line("2026-04-04T09:05:00.000Z", total=120, last=11),
        )
        assert [e.tokens.total for e in per_request] == [115, 11]
        assert [e.status for e in per_request] == [
            UsageStatus.MEASURED,
            UsageStatus.PARTIAL,
        ]


def _codex_usage(value):
    return {
        "input_tokens": value,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": value,
    }


class TestNachreview007a8ff:
    """Regressionstests zu den drei Befunden aus dem Review von
    007a8ff (siehe Beads ki-dev-ablauf-wu0.2, achter Nachreview)."""

    _line = TestNachreview19b6e88._line
    _per_request = TestNachreview19b6e88Folgerunde._per_request

    def test_reset_to_same_level_invalidates_confirmation(
        self, tmp_path
    ):
        """[P2] (115,115) -> (200,fehlt) -> (115,fehlt) -> (115,115):
        derselbe Zahlenwert nach einem Reset ist ein anderer
        Zaehlerabschnitt -- die alte Bestaetigung bei 115 darf die
        letzte Beobachtung nicht unterdruecken."""
        _, per_request = self._per_request(
            tmp_path,
            self._line("2026-04-04T09:00:00.000Z", total=115, last=115),
            self._line("2026-04-04T09:05:00.000Z", total=200),
            self._line("2026-04-04T09:10:00.000Z", total=115),
            self._line("2026-04-04T09:15:00.000Z", total=115, last=115),
        )
        assert [e.tokens.total for e in per_request] == [115, 115]
        assert [e.status for e in per_request] == [
            UsageStatus.MEASURED,
            UsageStatus.PARTIAL,
        ]

    def test_unordered_total_below_request_value_is_partial(
        self, tmp_path
    ):
        """[P2] Ohne Zeitstempel: eine intern gueltige Summe 5 deckt
        einen Request 11 nicht -- PARTIAL mit Diagnose, wie im
        geordneten Pfad."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            json.dumps(
                {
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "last_token_usage": _codex_usage(11),
                            "total_token_usage": _codex_usage(5),
                        },
                    },
                }
            )
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert [e.tokens.total for e in per_request] == [11]
        assert per_request[0].status is UsageStatus.PARTIAL
        assert "kleiner" in per_request[0].detail

    def test_invalid_intermediate_total_does_not_confirm(
        self, tmp_path
    ):
        """[P2] Ein Summenobjekt nur mit total_tokens (ohne
        Einzelzaehler) ist kein Beleg: der 11er-Request bleibt
        unbestaetigt sichtbar, auch wenn spaeter eine gueltige Summe
        folgt."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            _rollout_line(
                timestamp="2026-04-04T09:00:00.000Z",
                payload={
                    "type": "token_count",
                    "info": {
                        "total_token_usage": {"total_tokens": 11},
                        "last_token_usage": _codex_usage(11),
                    },
                },
            )
            + "\n"
            + self._line("2026-04-04T09:05:00.000Z", total=22, last=11)
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert [e.tokens.total for e in per_request] == [11, 11]
        assert [e.status for e in per_request] == [
            UsageStatus.PARTIAL,
            UsageStatus.MEASURED,
        ]


    def test_unconfirmed_value_does_not_cross_summary_change(
        self, tmp_path
    ):
        """Gleiche Klasse wie Befund 1: (115,115) -> (115,11) ->
        (200,fehlt) -> (200,11). Der 11er bei Stand 115 wird vom
        Wechsel auf 200 (Zuwachs 85) nicht bestaetigt; die 11 bei
        Stand 200 ist ein anderer Zaehlerabschnitt -- zwei
        unbestaetigte Lesungen, nicht eine."""
        _, per_request = self._per_request(
            tmp_path,
            self._line("2026-04-04T09:00:00.000Z", total=115, last=115),
            self._line("2026-04-04T09:05:00.000Z", total=115, last=11),
            self._line("2026-04-04T09:10:00.000Z", total=200),
            self._line("2026-04-04T09:15:00.000Z", total=200, last=11),
        )
        assert [e.tokens.total for e in per_request] == [115, 11, 11]
        assert [e.status for e in per_request] == [
            UsageStatus.MEASURED,
            UsageStatus.PARTIAL,
            UsageStatus.PARTIAL,
        ]

    def test_unconfirmed_value_merges_with_confirming_change(
        self, tmp_path
    ):
        """Gegenprobe: (0,fehlt) -> (0,5) -> (5,5) -- der Wechsel auf
        5 (Zuwachs genau 5) bestaetigt die zuvor unbestaetigte Lesung;
        eine MEASURED-Anfrage, keine zweite."""
        _, per_request = self._per_request(
            tmp_path,
            self._line("2026-04-04T09:00:00.000Z", total=0),
            self._line("2026-04-04T09:05:00.000Z", total=0, last=5),
            self._line("2026-04-04T09:10:00.000Z", total=5, last=5),
        )
        assert [e.tokens.total for e in per_request] == [5]
        assert per_request[0].status is UsageStatus.MEASURED

    def test_unknown_version_merges_confirmed_repetition(
        self, tmp_path
    ):
        """Festgelegt: der Vergleichswert eines Requests ist
        unabhaengig von der CLI-Version. (fehlt,11) -> (11,11) ohne
        bekannte Version ist genau eine Lesung (PARTIAL wegen
        Version), nicht zwei."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            self._line("2026-04-04T09:00:00.000Z", last=11)
            + "\n"
            + self._line("2026-04-04T09:05:00.000Z", total=11, last=11)
            + "\n"
        )
        scan = read_codex_rollout_usage(path, cli_version=None)
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert [e.tokens.total for e in per_request] == [11]
        assert per_request[0].status is UsageStatus.PARTIAL

    def test_unknown_version_keeps_contradiction_detail(
        self, tmp_path
    ):
        """Die Widerspruchs-Diagnose darf nicht verloren gehen, nur
        weil das Ereignis ohnehin schon (wegen unbekannter Version)
        PARTIAL ist."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            self._line("2026-04-04T09:00:00.000Z", total=5, last=11)
            + "\n"
        )
        scan = read_codex_rollout_usage(path, cli_version=None)
        per_request = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]
        assert len(per_request) == 1
        assert per_request[0].status is UsageStatus.PARTIAL
        assert "kleiner" in per_request[0].detail
        assert "cli_version" in per_request[0].detail

    def test_reset_and_invalid_intermediate_both_visible(
        self, tmp_path
    ):
        """(115) -> (ungueltig 11) -> (50) -> (200): Rueckgang und
        ungueltige Zwischensumme muessen beide in der Diagnose der
        Gesamtsumme stehen."""
        path = tmp_path / "rollout.jsonl"
        path.write_text(
            self._line("2026-04-04T09:00:00.000Z", total=115)
            + "\n"
            + _rollout_line(
                timestamp="2026-04-04T09:05:00.000Z",
                payload={
                    "type": "token_count",
                    "info": {"total_token_usage": {"total_tokens": 11}},
                },
            )
            + "\n"
            + self._line("2026-04-04T09:10:00.000Z", total=50)
            + "\n"
            + self._line("2026-04-04T09:15:00.000Z", total=200)
            + "\n"
        )
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        (cumulative,) = [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.CUMULATIVE_SESSION
        ]
        assert cumulative.status is UsageStatus.PARTIAL
        assert "gesunken" in cumulative.detail
        assert "ungueltig" in cumulative.detail

_VALUES = [0, 5, 11, 22, 115, 126, 200]

# Ein Rollout-Schritt: (Summe, Requestwert, mit Zeitstempel). Summe ist
# None (fehlt), ("ok", v) (voll gueltig) oder ("bad", v) (nur
# total_tokens, ohne Einzelzaehler -- strukturell ungueltig).
_rollout_steps = st.lists(
    st.tuples(
        st.one_of(
            st.none(),
            st.tuples(
                st.sampled_from(["ok", "bad"]), st.sampled_from(_VALUES)
            ),
        ),
        st.one_of(st.none(), st.sampled_from([5, 11, 115])),
        # ueberwiegend mit Zeitstempel, einzelne ohne
        st.sampled_from([True, True, True, False]),
    ).filter(lambda step: step[:2] != (None, None)),
    min_size=1,
    max_size=6,
)


def _rollout_step_line(index, total, last, ordered):
    info = {}
    if total is not None:
        kind, value = total
        info["total_token_usage"] = (
            _codex_usage(value)
            if kind == "ok"
            else {"total_tokens": value}
        )
    if last is not None:
        info["last_token_usage"] = _codex_usage(last)
    row = {
        "type": "event_msg",
        "payload": {"type": "token_count", "info": info},
    }
    if ordered:
        row["timestamp"] = f"2026-04-04T09:{index:02d}:00.000Z"
    return json.dumps(row)


def _rollout_oracle(steps):
    """Unabhaengig von der Implementierung aus den Eingaben
    abgeleitete Schranken (nur voll gueltige Summen zaehlen als
    Beleg):

    - ``budget``: was die Summen hoechstens an MEASURED-Requests
      belegen -- im geordneten Pfad Zuwachs bzw. nach Reset/erster
      Summe die neue Basis, ohne Zeitstempel die eigene Summe.
    - ``minimum``: je Requestwert die Mindestzahl an Ausgaben. Jeder
      Wechsel der gueltigen Summe (auch ein Reset zurueck auf
      denselben Zahlenwert) beginnt einen neuen Zaehlerabschnitt.
      Eine Beobachtung mit gueltiger Summe gehoert zu ihrem Abschnitt
      und verschmilzt nur innerhalb davon -- oder, solange sie
      unbestaetigt ist, mit genau dem Ereignis, dessen Summenwechsel
      den naechsten Abschnitt beginnt."""
    budget = 0
    previous = None
    segment = 0
    # Wert -> Abschnitte mit Beobachtung / mit bestaetigendem Ereignis
    # (Summenwechsel) / mit Beobachtung bei unveraenderter Summe
    seen: dict[int, set[int]] = {}
    opening: dict[int, set[int]] = {}
    unchanged: dict[int, set[int]] = {}
    for total, last, ordered in steps:
        valid = (
            total[1] if total is not None and total[0] == "ok" else None
        )
        if not ordered:
            if valid is not None and last is not None:
                budget += valid
            continue
        changed = valid is not None and valid != previous
        if changed:
            segment += 1
            budget += (
                valid - previous
                if previous is not None and valid > previous
                else valid
            )
            previous = valid
        if valid is not None and last is not None:
            seen.setdefault(last, set()).add(segment)
            target = opening if changed else unchanged
            target.setdefault(last, set()).add(segment)
    minimum = {
        value: len(segments)
        - sum(
            1
            for seg in unchanged.get(value, set())
            if seg + 1 in opening.get(value, set())
        )
        for value, segments in seen.items()
    }
    return budget, minimum


@settings(max_examples=500, deadline=None)
@given(steps=_rollout_steps)
def test_codex_rollout_request_invariants(steps):
    """Invarianten statt Einzelbeispielen (die Nachreview-Runden zu
    wu0.2 haben gezeigt, dass Einzelfall-Korrekturen neue
    Gegenbeispiele erzeugen). Deckt geordneten und zeitstempellosen
    Pfad, gueltige und ungueltige Summen sowie Resets ab:

    1. Keine beobachtete last_token_usage-Lesung verschwindet
       stillschweigend -- jeder Wert erscheint mindestens einmal, und
       mindestens so oft, wie er in verschiedenen Zaehlerabschnitten
       mit gueltiger Summe beobachtet wurde.
    2. Die MEASURED-Requests zusammen uebersteigen nie, was die
       gueltigen Summen belegen.
    3. Keine Vervielfachung: hoechstens so viele Requests wie
       beobachtete last_token_usage-Lesungen.
    4. Mehrfachlesen ist idempotent.
    5. Eine strukturell ungueltige Summe ist kein Beleg: die
       Request-Ergebnisse sind dieselben wie ganz ohne diese Summe.
    6. Gesamtsumme: gab es im geordneten Pfad einen Rueckgang oder
       eine ungueltige Summe, ist sie nie MEASURED, und ihre Diagnose
       nennt jede zutreffende Ursache (keine verdraengt die andere)."""

    def scan_steps(steps, tmp):
        lines = [
            _rollout_step_line(index, total, last, ordered)
            for index, (total, last, ordered) in enumerate(steps)
        ]
        path = Path(tmp) / "rollout.jsonl"
        path.write_text("\n".join(lines) + "\n")
        scan = read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        assert scan == read_codex_rollout_usage(
            path, cli_version=CODEX_CLI_VERSION
        )
        return scan

    without_bad = [
        (None if total is not None and total[0] == "bad" else total,)
        + step[1:]
        for step in steps
        for total in [step[0]]
    ]
    def requests(scan):
        return [
            e
            for e in scan.events
            if e.counter_scope is CounterScope.PER_REQUEST
        ]

    with tempfile.TemporaryDirectory() as tmp:
        scan = scan_steps(steps, tmp)
        per_request = requests(scan)
        assert per_request == requests(scan_steps(without_bad, tmp))
    cumulative = [
        e
        for e in scan.events
        if e.counter_scope is CounterScope.CUMULATIVE_SESSION
    ]
    ordered_totals = [
        total for total, _, ordered in steps if ordered and total
    ]
    valid_ordered = [v for kind, v in ordered_totals if kind == "ok"]
    had_reset = any(
        later < earlier
        for earlier, later in zip(
            valid_ordered, valid_ordered[1:], strict=False
        )
    )
    had_bad = any(kind == "bad" for kind, _ in ordered_totals)
    assert len(cumulative) == (1 if ordered_totals else 0)
    if had_reset or had_bad:
        assert cumulative[0].status is not UsageStatus.MEASURED
    if had_reset:
        assert "gesunken" in cumulative[0].detail
    if had_bad:
        assert "ungueltig" in cumulative[0].detail
    lasts = [last for _, last, _ in steps if last is not None]
    budget, minimum = _rollout_oracle(steps)
    output_values = [e.tokens.total for e in per_request]
    assert set(lasts) <= set(output_values)
    for value, count in minimum.items():
        assert output_values.count(value) >= count
    assert len(per_request) <= len(lasts)
    measured = sum(
        e.tokens.total
        for e in per_request
        if e.status is UsageStatus.MEASURED
    )
    assert measured <= budget
