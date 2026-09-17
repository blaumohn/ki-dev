"""Tests fuer den Tokenmessvertrag (ki-dev-ablauf-wu0.2).

Fixtures spiegeln real beobachtete Feldnamen/-beziehungen aus lokalen
Codex-Rollouts und Claude-Sitzungstranskripten wider (Schema per
gezielter Feldnamen-/Zaehlerpruefung verifiziert, nie per Rohinhalt-
Lesen -- siehe usage.py-Moduldoc und AGENTS.md). Die konkreten Werte
in diesen Tests sind erfunden, ihre Struktur/Beziehungen nicht.
"""

from __future__ import annotations

import pytest

from ki_dev.usage import (
    CounterScope,
    TokenCounts,
    UsageEvent,
    UsageStatus,
    normalize_claude_cli_result,
    normalize_claude_session_message_usage,
    normalize_codex_token_count_usage,
    normalize_codex_turn_usage,
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
            self._usage(), cli_version="2.1.272", session_id="s1"
        )
        assert event.status is UsageStatus.MEASURED
        assert event.provider == "claude"
        assert event.source == "cli_result"
        assert event.counter_scope is CounterScope.PER_REQUEST
        assert event.tokens == TokenCounts(10, 500, 30, 20)
        assert event.cli_version == "2.1.272"
        assert event.session_id == "s1"

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
            self._usage(), confirmed_model="claude-haiku-4-5-20251001"
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
        event = normalize_claude_session_message_usage(usage)
        assert event.status is UsageStatus.MEASURED
        assert event.tokens.reasoning_output is None
        assert event.tokens.cache_creation_ephemeral_5m is None

    def test_inconsistent_ephemeral_split_is_partial_not_dropped(self):
        usage = self._usage(
            cache_creation={
                "ephemeral_5m_input_tokens": 7,
                "ephemeral_1h_input_tokens": 999,
            }
        )
        event = normalize_claude_session_message_usage(usage)
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
            }
        )
        assert event.status is UsageStatus.MEASURED
        assert event.tokens.fresh_input == 60
        assert event.tokens.cache_read == 40
        assert event.tokens.output == 15

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
        )
        assert event.status is UsageStatus.MEASURED
        assert event.source == "rollout_last_token_usage"
        assert event.tokens.fresh_input == 60
        assert event.tokens.reasoning_output == 3

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
