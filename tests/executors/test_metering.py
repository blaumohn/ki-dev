from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ki_dev.adapter.executors import (
    ClaudeCliAdapter,
    CodexCliAdapter,
    Effort,
)
from ki_dev.adapter.executors.contract import (
    ContextStatus,
    QuotaStatus,
    TurnBudget,
    TurnRequest,
    TurnResult,
    TurnStatus,
)
from ki_dev.adapter.executors.metering import (
    claude_context_tokens,
    claude_result,
    codex_quota,
    codex_result,
)
from ki_dev.usage import CounterScope, TokenCounts, UsageStatus

from .conftest import FakeRunner
from .usage_fakes import write_usage_cli


def _result(stdout, **kwargs):
    return replace(
        TurnResult(TurnStatus.OK, 0, stdout, "", (), 1.0), **kwargs
    )


def _claude(**kwargs):
    value = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": "fertig",
        "num_turns": 3,
        "total_cost_usd": 0.2,
        "usage": {
            "input_tokens": 10,
            "output_tokens": 20,
            "cache_read_input_tokens": 500,
            "cache_creation_input_tokens": 30,
        },
        "permission_denials": [],
    }
    value.update(kwargs)
    return json.dumps(value)


def test_claude_usage_and_answer_are_separate():
    result = claude_result(_result(_claude()))
    assert result.ok
    assert result.stdout == "fertig"
    assert result.usage == {
        "input_tokens": 10,
        "output_tokens": 20,
        "cache_read_input_tokens": 500,
        "cache_creation_input_tokens": 30,
        "num_turns": 3,
        "cost_usd": 0.2,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"subtype": "error_max_turns", "is_error": True},
        {"subtype": "error_max_budget_usd", "is_error": True},
        {"result": "You've hit your session limit", "is_error": True},
        {"permission_denials": [{"tool_name": "Read"}]},
    ],
)
def test_zero_exit_is_not_success_on_provider_blocker(changes):
    result = claude_result(_result(_claude(**changes)))
    assert not result.ok
    assert result.usage["cost_usd"] == 0.2
    assert result.error


@pytest.mark.parametrize(
    "stdout",
    [
        "fertig",
        "[]",
        _claude(usage=None),
        _claude(total_cost_usd=float("nan")),
        _claude(num_turns=True),
    ],
)
def test_missing_or_invalid_claude_usage_is_a_stop(stdout):
    assert not claude_result(_result(stdout)).ok


def test_provider_failure_preserves_diagnostic():
    result = claude_result(
        _result(
            "You've hit your session limit",
            status=TurnStatus.NONZERO_EXIT,
            exit_code=1,
            error="CLI endete mit Exitstatus 1",
        )
    )
    assert "session limit" in result.error


def _session(root, usage):
    path = root / "workspace" / "session.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "model": "claude",
                    "usage": usage,
                },
            }
        )
        + "\n"
        + json.dumps(
            {
                "type": "assistant",
                "message": {
                    "model": "<synthetic>",
                    "usage": {"input_tokens": 0},
                },
            }
        )
        + "\n"
    )


def test_context_preflight_counts_cached_input_and_skips_synthetic(
    tmp_path,
):
    _session(
        tmp_path,
        {
            "input_tokens": 2,
            "cache_creation_input_tokens": 100,
            "cache_read_input_tokens": 90_000,
        },
    )
    assert claude_context_tokens("session", tmp_path) == 90_102


def _request():
    return TurnRequest(
        "session",
        "auftrag",
        "model",
        Effort.MEDIUM,
        Path("/work"),
        budget=TurnBudget(),
    )


def test_claude_measure_context_reports_real_value(monkeypatch):
    """Die Kontextvorpruefung ist keine Aufgabe des Adapters mehr
    (ki-dev-ablauf-agu): ``measure_context`` liefert nur den
    Messwert, ohne den naechsten Aufruf selbst zu verhindern."""
    monkeypatch.setattr(
        "ki_dev.adapter.executors.claude_cli.claude_context_tokens",
        lambda *_: 90_000,
    )
    measurement = ClaudeCliAdapter().measure_context("session")
    assert measurement.status is ContextStatus.MEASURED
    assert measurement.tokens == 90_000


def test_claude_measure_context_reports_unavailable_explicitly(
    monkeypatch,
):
    def _raise(*_args):
        raise ValueError("Claude-Sitzung hat keinen Verbrauchsnachweis")

    monkeypatch.setattr(
        "ki_dev.adapter.executors.claude_cli.claude_context_tokens",
        _raise,
    )
    measurement = ClaudeCliAdapter().measure_context("session")
    assert measurement.status is ContextStatus.UNAVAILABLE
    assert measurement.tokens is None
    assert "Verbrauchsnachweis" in measurement.detail


def test_codex_measure_context_is_explicitly_unsupported():
    measurement = CodexCliAdapter().measure_context("session")
    assert measurement.status is ContextStatus.UNSUPPORTED
    assert measurement.tokens is None


def _token_count_line(
    *,
    used_percent: float,
    resets_at: int,
    window_minutes: int = 300,
    timestamp: str = "2026-09-17T10:07:56.544Z",
) -> dict:
    """Rollout-Zeile im echten, lokal beobachteten Codex-Schema
    (``originator: codex_exec``, Ereignis ``token_count``) -- keine
    erfundene Struktur, siehe ki-dev-ablauf-hju."""
    return {
        "timestamp": timestamp,
        "ordinal": 435,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {
                "total_token_usage": {
                    "input_tokens": 3_050_487,
                    "cached_input_tokens": 2_942_592,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 11_448,
                    "reasoning_output_tokens": 3_683,
                    "total_tokens": 3_061_935,
                },
                "last_token_usage": {
                    "input_tokens": 112_884,
                    "cached_input_tokens": 112_384,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 161,
                    "reasoning_output_tokens": 58,
                    "total_tokens": 113_045,
                },
                "model_context_window": 258_400,
            },
            "rate_limits": {
                "limit_id": "codex",
                "limit_name": None,
                "primary": {
                    "used_percent": used_percent,
                    "window_minutes": window_minutes,
                    "resets_at": resets_at,
                },
                "secondary": {
                    "used_percent": 28.0,
                    "window_minutes": 10_080,
                    "resets_at": resets_at + 500_000,
                },
                "credits": {
                    "has_credits": False,
                    "unlimited": False,
                    "balance": "0",
                },
                "individual_limit": None,
                "spend_control_reached": None,
                "plan_type": "plus",
                "rate_limit_reached_type": None,
            },
        },
    }


def _rollout_path(root: Path, session_id: str) -> Path:
    directory = root / "2026" / "09" / "17"
    directory.mkdir(parents=True, exist_ok=True)
    return (
        directory / f"rollout-2026-09-17T09-10-35-{session_id}.jsonl"
    )


def _rollout(
    root: Path,
    session_id: str,
    *,
    used_percent: float,
    resets_at: int,
    window_minutes: int = 300,
    timestamp: str = "2026-09-17T10:07:56.544Z",
) -> None:
    _rollout_path(root, session_id).write_text(
        json.dumps(
            _token_count_line(
                used_percent=used_percent,
                resets_at=resets_at,
                window_minutes=window_minutes,
                timestamp=timestamp,
            )
        )
        + "\n"
    )


def _rollout_lines(
    root: Path, session_id: str, lines: list[dict]
) -> None:
    """Wie ``_rollout``, aber mehrere Zeilen in physischer
    Reihenfolge -- fuer Tests, die eine nicht chronologisch sortierte
    Zeilenfolge innerhalb einer Datei simulieren."""
    _rollout_path(root, session_id).write_text(
        "".join(json.dumps(line) + "\n" for line in lines)
    )


def _iso(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _epoch(timestamp: str) -> float:
    return datetime.fromisoformat(
        timestamp.replace("Z", "+00:00")
    ).timestamp()


def _touch(path: Path, mtime: float) -> None:
    os.utime(path, (mtime, mtime))


def _rollout_without_quota(root: Path, session_id: str) -> Path:
    """Rollout-Datei ohne token_count-Ereignis -- z.B. eine Sitzung,
    die noch keine Kontingentmessung geschrieben hat."""
    directory = root / "2026" / "09" / "17"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"rollout-2026-09-17T09-10-35-{session_id}.jsonl"
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-09-17T09:10:35.000Z",
                "type": "event_msg",
                "payload": {"type": "task_started"},
            }
        )
        + "\n"
    )
    return path


def test_codex_quota_reads_last_five_hour_snapshot(tmp_path):
    _rollout(
        tmp_path, "thread-1", used_percent=13.0, resets_at=9_999_999_999
    )
    now = _epoch("2026-09-17T10:07:56.544Z") + 10
    assert codex_quota("thread-1", tmp_path, now=now) == (
        13.0,
        9_999_999_999,
    )


def test_codex_quota_rejects_expired_snapshot_instead_of_zero(tmp_path):
    """Ein Messwert aus einem bereits zurueckgesetzten Fenster ist kein
    Nachweis fuer den aktuellen Verbrauch (Claude-Changelog 2.1.x kennt
    denselben Fehlerfall fuer Statuszeilen)."""
    _rollout(tmp_path, "thread-1", used_percent=13.0, resets_at=100)
    with pytest.raises(ValueError, match="abgelaufen"):
        codex_quota("thread-1", tmp_path, now=200)


def test_codex_quota_requires_the_five_hour_window_not_position(
    tmp_path,
):
    _rollout(
        tmp_path,
        "thread-1",
        used_percent=13.0,
        resets_at=9_999_999_999,
        window_minutes=10_080,
    )
    with pytest.raises(ValueError, match="5h-Fenster"):
        codex_quota("thread-1", tmp_path, now=0)


def test_codex_quota_missing_rollout_is_a_stop(tmp_path):
    with pytest.raises(ValueError, match="fehlt"):
        codex_quota("thread-1", tmp_path)


def test_codex_quota_uses_freshest_snapshot_not_own_stale_session(
    tmp_path,
):
    """Das Kontingent ist kontoweit, nicht sitzungsgebunden: eine
    Rolle, deren eigene Sitzung laenger nicht mit der API gesprochen
    hat, darf keinen veralteten, zu niedrigen Wert liefern, waehrend
    eine andere Sitzung desselben Kontos das Kontingent
    zwischenzeitlich weiter verbraucht hat."""
    _rollout(
        tmp_path,
        "thread-own",
        used_percent=10.0,
        resets_at=9_999_999_999,
        timestamp="2026-09-17T08:00:00.000Z",
    )
    _rollout(
        tmp_path,
        "thread-other",
        used_percent=95.0,
        resets_at=9_999_999_999,
        timestamp="2026-09-17T10:00:00.000Z",
    )
    now = _epoch("2026-09-17T10:00:00.000Z") + 10
    assert codex_quota("thread-own", tmp_path, now=now) == (
        95.0,
        9_999_999_999,
    )


def test_codex_quota_ignores_own_stale_snapshot_when_it_is_older(
    tmp_path,
):
    """Symmetrischer Fall: die eigene Sitzung ist die juengste --
    Vorrang bleibt unabhaengig davon, welche Sitzung geprueft wird."""
    _rollout(
        tmp_path,
        "thread-own",
        used_percent=95.0,
        resets_at=9_999_999_999,
        timestamp="2026-09-17T10:00:00.000Z",
    )
    _rollout(
        tmp_path,
        "thread-other",
        used_percent=10.0,
        resets_at=9_999_999_999,
        timestamp="2026-09-17T08:00:00.000Z",
    )
    now = _epoch("2026-09-17T10:00:00.000Z") + 10
    assert codex_quota("thread-own", tmp_path, now=now) == (
        95.0,
        9_999_999_999,
    )


def test_codex_quota_is_not_excluded_by_many_newer_files_without_it(
    tmp_path,
):
    """Ein fester Dateien-Deckel waehlt Kandidaten nach Datei-
    Aenderungszeit vor, den Treffer aber nach Ereigniszeit aus --
    zwei verschiedene Kriterien. Viele neuere Dateien OHNE
    Kontingentmessung duerfen die Datei mit der tatsaechlich
    einzigen/juengsten Messung nicht aus der Suche verdraengen
    (ki-dev-ablauf-dqv-Nachreview, lokal reproduziert)."""
    now = 2_000_000_000.0
    _rollout(
        tmp_path,
        "thread-real",
        used_percent=95.0,
        resets_at=int(now) + 10_000,
        timestamp=_iso(now - 300),
    )
    _touch(
        tmp_path
        / "2026"
        / "09"
        / "17"
        / "rollout-2026-09-17T09-10-35-thread-real.jsonl",
        now - 250,
    )
    for i in range(25):
        path = _rollout_without_quota(tmp_path, f"thread-noise-{i}")
        _touch(path, now - i)
    assert codex_quota("thread-real", tmp_path, now=now) == (
        95.0,
        int(now) + 10_000,
    )


def test_codex_quota_prefers_newer_event_despite_older_mtime(tmp_path):
    """Ein Ereignis-Zeitstempel im Dateiinhalt muss nicht kleiner als
    die Datei-Aenderungszeit sein (Kopien, Wiederherstellung,
    verzoegertes Schreiben); die Suche darf sich darauf nicht
    verlassen. Datei A hat die juengere mtime, aber den aelteren
    Messwert; Datei B umgekehrt -- das tatsaechlich juengste Ereignis
    (Datei B) muss trotzdem gewinnen (ki-dev-ablauf-dqv-Nachreview,
    lokal reproduziert)."""
    now = 2_000_000_000.0
    _rollout(
        tmp_path,
        "thread-a",
        used_percent=10.0,
        resets_at=int(now) + 10_000,
        timestamp=_iso(now - 500),
    )
    _touch(
        tmp_path
        / "2026"
        / "09"
        / "17"
        / "rollout-2026-09-17T09-10-35-thread-a.jsonl",
        now - 10,
    )
    _rollout(
        tmp_path,
        "thread-b",
        used_percent=95.0,
        resets_at=int(now) + 10_000,
        timestamp=_iso(now - 50),
    )
    _touch(
        tmp_path
        / "2026"
        / "09"
        / "17"
        / "rollout-2026-09-17T09-10-35-thread-b.jsonl",
        now - 400,
    )
    assert codex_quota("thread-a", tmp_path, now=now) == (
        95.0,
        int(now) + 10_000,
    )


def test_codex_quota_compares_timestamps_as_time_not_text(tmp_path):
    """'...:00Z' sortiert lexikografisch NACH '...:00.500Z' ('.' <
    'Z' in ASCII), obwohl Ersteres 500ms frueher ist. Der Vergleich
    muss ueber geparste Zeitwerte laufen, nicht ueber die Zeitstempel-
    Strings (ki-dev-ablauf-dqv-Nachreview, lokal reproduziert)."""
    earlier_ts = "2026-09-17T05:00:00Z"
    later_ts = "2026-09-17T05:00:00.500Z"
    assert later_ts < earlier_ts  # als Text irrefuehrend sortiert
    now = _epoch(later_ts) + 10
    _rollout(
        tmp_path,
        "thread-earlier",
        used_percent=10.0,
        resets_at=int(now) + 10_000,
        timestamp=earlier_ts,
    )
    _rollout(
        tmp_path,
        "thread-later",
        used_percent=95.0,
        resets_at=int(now) + 10_000,
        timestamp=later_ts,
    )
    assert codex_quota("thread-earlier", tmp_path, now=now) == (
        95.0,
        int(now) + 10_000,
    )


def test_codex_quota_picks_max_timestamp_within_a_single_file(
    tmp_path,
):
    """Innerhalb einer Datei gewinnt der groesste geparste Zeitwert,
    nicht die physisch letzte Zeile -- eine chronologisch sortierte
    Zeilenfolge ist technisch nicht garantiert. Zeile 1 traegt den
    juengeren Zeitstempel, Zeile 2 (spaeter in der Datei) einen
    aelteren -- der juengere Wert muss trotzdem gewinnen
    (ki-dev-ablauf-dqv-Nachreview, lokal reproduziert)."""
    now = _epoch("2026-09-17T05:00:00.500Z") + 10
    _rollout_lines(
        tmp_path,
        "thread-1",
        [
            _token_count_line(
                used_percent=95.0,
                resets_at=int(now) + 10_000,
                timestamp="2026-09-17T05:00:00.500Z",
            ),
            _token_count_line(
                used_percent=10.0,
                resets_at=int(now) + 10_000,
                timestamp="2026-09-17T05:00:00Z",
            ),
        ],
    )
    assert codex_quota("thread-1", tmp_path, now=now) == (
        95.0,
        int(now) + 10_000,
    )


def test_codex_quota_rejects_future_timestamp(tmp_path):
    """Ein Zeitstempel merklich nach 'now' ist kein Uhrenversatz mehr,
    sondern ein unplausibler Wert -- ein negatives Alter darf die
    Altersschwelle nicht unkritisch bestehen (ki-dev-ablauf-dqv-
    Nachreview, lokal reproduziert)."""
    now = 2_000_000_000.0
    _rollout(
        tmp_path,
        "thread-1",
        used_percent=50.0,
        resets_at=int(now) + 10_000,
        timestamp=_iso(now + 3600),
    )
    with pytest.raises(ValueError, match="Zukunft"):
        codex_quota("thread-1", tmp_path, now=now)


def test_codex_quota_accepts_a_recent_event(tmp_path):
    now = 2_000_000_000.0
    _rollout(
        tmp_path,
        "thread-1",
        used_percent=50.0,
        resets_at=int(now) + 10_000,
        timestamp=_iso(now - 60),
    )
    assert codex_quota("thread-1", tmp_path, now=now) == (
        50.0,
        int(now) + 10_000,
    )


def test_codex_quota_rejects_stale_event_despite_unexpired_window(
    tmp_path,
):
    """Ein Fenster, das laut resets_at noch nicht abgelaufen ist,
    beweist keine Aktualitaet: ein mehrere Stunden alter Messwert wird
    nicht mehr als Naeherung des aktuellen Kontostands akzeptiert
    (ki-dev-ablauf-dqv-Nachreview, lokal reproduziert)."""
    now = 2_000_000_000.0
    _rollout(
        tmp_path,
        "thread-1",
        used_percent=50.0,
        resets_at=int(now) + 10_000,
        timestamp=_iso(now - 7200),
    )
    with pytest.raises(ValueError, match="zu alt"):
        codex_quota("thread-1", tmp_path, now=now)


def test_codex_measure_quota_reports_real_value(monkeypatch):
    monkeypatch.setattr(
        "ki_dev.adapter.executors.codex_cli.codex_quota",
        lambda *_: (42.0, 9_999_999_999),
    )
    measurement = CodexCliAdapter().measure_quota("session")
    assert measurement.status is QuotaStatus.MEASURED
    assert measurement.used_percent == 42.0
    assert measurement.resets_at == 9_999_999_999


def test_codex_measure_quota_reports_unavailable_explicitly(
    monkeypatch,
):
    def _raise(*_args):
        raise ValueError("Codex-Rollout hat keine 5h-Kontingentmessung")

    monkeypatch.setattr(
        "ki_dev.adapter.executors.codex_cli.codex_quota", _raise
    )
    measurement = CodexCliAdapter().measure_quota("session")
    assert measurement.status is QuotaStatus.UNAVAILABLE
    assert "Kontingentmessung" in measurement.detail


def test_claude_measure_quota_is_explicitly_unsupported():
    """Kein verbrauchsfreier, nicht-interaktiver Messweg bei Claude
    verifiziert (ki-dev-ablauf-hju); anders als bei ``measure_context``
    blockiert das den naechsten Aufruf (siehe ``_quota_guard``)."""
    measurement = ClaudeCliAdapter().measure_quota("session")
    assert measurement.status is QuotaStatus.UNSUPPORTED
    assert measurement.used_percent is None


def test_bounded_claude_uses_native_limits_and_timeout():
    """calls[0] ist die --version-Probe (R5, ki-dev-ablauf-wu0.3,
    VERSION_PROBE_TIMEOUT_S), calls[-1] der eigentliche Turn: er teilt
    sich die Rollen-Frist mit der Probe statt sie zu verdoppeln, daher
    knapp unter statt exakt 180."""
    runner = FakeRunner(_result(_claude()))
    result = ClaudeCliAdapter(runner=runner).send_turn(_request())
    assert result.ok
    assert runner.value_after("--output-format") == "json"
    assert runner.value_after("--max-turns") == "12"
    assert runner.value_after("--max-budget-usd") == "1.0"
    assert 179 < runner.calls[-1][2] <= 180


def _codex():
    return "\n".join(
        json.dumps(event)
        for event in [
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": "pruefe noch",
                },
            },
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": '{"event":"PASS"}',
                },
            },
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 1000,
                    "cached_input_tokens": 900,
                    "output_tokens": 50,
                },
            },
        ]
    )


def test_codex_usage_does_not_double_count_cached_input():
    """calls[0] ist die --version-Probe (R5, ki-dev-ablauf-wu0.3,
    VERSION_PROBE_TIMEOUT_S), calls[-1] der eigentliche Turn: er teilt
    sich die Rollen-Frist mit der Probe statt sie zu verdoppeln, daher
    knapp unter statt exakt 180."""
    runner = FakeRunner(_result(_codex()))
    result = CodexCliAdapter(runner=runner).send_turn(_request())
    assert result.stdout == '{"event":"PASS"}'
    assert result.usage["input_tokens"] == 100
    assert result.usage["cache_read_input_tokens"] == 900
    assert "--json" in runner.argv
    assert 179 < runner.calls[-1][2] <= 180


class _MonotonicSequence:
    """Liefert vorgegebene ``time.monotonic()``-Werte der Reihe nach --
    fuer deterministische Tests der geteilten Zeitgrenze aus
    ``CliAdapter.send_metered_turn`` (R5, ki-dev-ablauf-wu0.3), ohne
    tatsaechlich zu warten."""

    def __init__(self, values):
        self._values = iter(values)

    def __call__(self):
        return next(self._values)


@pytest.mark.parametrize(
    ("adapter_type", "turn_output"),
    [(ClaudeCliAdapter, _claude()), (CodexCliAdapter, _codex())],
    ids=["claude", "codex"],
)
def test_slow_version_probe_shrinks_turn_timeout_not_doubles_it(
    monkeypatch, adapter_type, turn_output
):
    """R5: Probe und Turn teilen sich EINE Zeitgrenze. Eine 150s
    dauernde Probe darf den Turn nicht erneut mit den vollen 180s
    laufen lassen, sondern nur mit den verbleibenden 30s -- sonst kann
    ein budgetierter Aufruf bis zu doppelt so lange dauern wie in
    docs/cli-adapters.md dokumentiert."""
    runner = FakeRunner(_result(turn_output))
    monkeypatch.setattr(
        "ki_dev.adapter.executors.base.time.monotonic",
        _MonotonicSequence([0.0, 150.0]),
    )
    adapter_type(runner=runner).send_turn(_request())
    assert len(runner.calls) == 2
    assert runner.calls[0][2] == pytest.approx(10.0)
    assert runner.calls[1][2] == pytest.approx(30.0)


@pytest.mark.parametrize(
    ("adapter_type", "turn_output"),
    [(ClaudeCliAdapter, _claude()), (CodexCliAdapter, _codex())],
    ids=["claude", "codex"],
)
def test_version_probe_exhausting_deadline_skips_the_turn(
    monkeypatch, adapter_type, turn_output
):
    """R5: Ist das Rollen-Budget bereits durch die Probe aufgebraucht,
    startet kein weiterer Prozess -- kein CLI-Aufruf, der die
    dokumentierte gemeinsame Zeitgrenze insgesamt ueberschreitet. Das
    TurnResult eines nicht gestarteten Turns geht NICHT durch
    claude_result()/codex_result(): deren Erfolgs-/Fehlerauswertung
    ist fuer ein tatsaechliches Prozessergebnis gebaut und wuerde
    TurnStatus.TIMEOUT sonst auf NONZERO_EXIT abbilden -- die vier
    TurnStatus-Werte sind laut Vertrag bewusst disjunkt."""
    runner = FakeRunner(_result(turn_output))
    monkeypatch.setattr(
        "ki_dev.adapter.executors.base.time.monotonic",
        _MonotonicSequence([0.0, 200.0]),
    )
    result = adapter_type(runner=runner).send_turn(_request())
    assert len(runner.calls) == 1
    assert not result.ok
    assert result.status is TurnStatus.TIMEOUT
    assert result.usage is None
    assert result.usage_event is None


class _SequencedRunner:
    """Liefert vorgegebene TurnResults der Reihe nach -- fuer Tests,
    die Probe- und Turn-Aufruf unterschiedlich beantworten muessen
    (anders als ``FakeRunner``, das jedem Aufruf dasselbe Ergebnis
    gibt)."""

    def __init__(self, results):
        self._results = iter(results)
        self.calls: list[tuple[tuple[str, ...], str, float]] = []

    def __call__(self, argv, *, stdin, timeout_s, **kwargs):
        del kwargs
        self.calls.append((tuple(argv), stdin, timeout_s))
        return next(self._results)


def _version_probe_result(provider: str) -> TurnResult:
    stdout = (
        f"{ClaudeCliAdapter.cli_version_pin} (Claude Code)"
        if provider == "claude"
        else f"codex-cli {CodexCliAdapter.cli_version_pin}"
    )
    return _result(stdout)


@pytest.mark.parametrize(
    ("adapter_type", "provider"),
    [(ClaudeCliAdapter, "claude"), (CodexCliAdapter, "codex")],
    ids=["claude", "codex"],
)
@pytest.mark.parametrize(
    "turn_result",
    [
        TurnResult(
            TurnStatus.TIMEOUT,
            None,
            "",
            "",
            (),
            180.0,
            error="Zeitueberschreitung nach 180s",
        ),
        TurnResult(
            TurnStatus.START_ERROR,
            None,
            "",
            "",
            (),
            0.0,
            error="Prozessstart fehlgeschlagen: CLI nicht auffindbar",
        ),
    ],
    ids=["timeout", "start_error"],
)
def test_real_process_failure_status_survives_result_postprocessing(
    adapter_type, provider, turn_result
):
    """Review-Nachtrag 2026-09-18 12:50, ki-dev-ablauf-wu0.3: ein real
    abgebrochener Turn-Prozess (TIMEOUT/START_ERROR, NACH einer
    erfolgreichen Versionsprobe) darf claude_result()/codex_result()
    nicht stillschweigend zu NONZERO_EXIT umdeuten -- die vier
    TurnStatus-Werte sind laut Vertrag bewusst disjunkt. Anders als
    ``test_version_probe_exhausting_deadline_skips_the_turn`` wird der
    Turn hier tatsaechlich gestartet; nur sein Prozessergebnis ist ein
    Nicht-Erfolg."""
    runner = _SequencedRunner(
        [_version_probe_result(provider), turn_result]
    )
    result = adapter_type(runner=runner).send_turn(_request())
    assert len(runner.calls) == 2
    assert result.status is turn_result.status
    assert result.usage is None
    assert result.usage_event is None


@pytest.mark.parametrize(
    ("exit_code", "with_error_event"),
    [(7, False), (0, True)],
)
def test_codex_failure_preserves_completed_turn_usage(
    exit_code, with_error_event
):
    """Ein fehlgeschlagener CLI-Aufruf darf einen bereits belegten
    turn.completed-Verbrauch nicht verlieren (wu0.3/AC6).

    Synthetischer Robustheitsfall, kein Nachweis einer real
    beobachteten CLI-Ereignisfolge. Die Antwort selbst ist gueltig.
    """
    events = [
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "fertig"},
        },
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": 1000,
                "cached_input_tokens": 900,
                "output_tokens": 50,
            },
        }
    ]
    if with_error_event:
        events.append({"type": "error", "message": "failed"})
    raw = "\n".join(json.dumps(event) for event in events)
    result = codex_result(
        _result(
            raw,
            status=TurnStatus.OK
            if exit_code == 0
            else TurnStatus.NONZERO_EXIT,
            exit_code=exit_code,
        ),
        session_id="session",
        cli_version=CodexCliAdapter.cli_version_pin,
    )

    assert result.status is TurnStatus.NONZERO_EXIT
    assert result.exit_code == exit_code
    if result.usage is None:
        pytest.fail("Codex-Verbrauch aus turn.completed ging verloren")
    assert result.usage == {
        "input_tokens": 100,
        "cache_read_input_tokens": 900,
        "cache_creation_input_tokens": 0,
        "output_tokens": 50,
    }
    event = result.usage_event
    assert event is not None
    assert event.status is UsageStatus.MEASURED
    assert event.provider == "codex"
    assert event.source == "cli_turn_completed"
    assert event.counter_scope is CounterScope.CALL_TOTAL
    assert event.session_id == "session"
    assert event.tokens == TokenCounts(100, 900, 0, 50)


@pytest.mark.parametrize(
    ("adapter_type", "provider", "turn_output", "expected_tokens"),
    [
        (
            ClaudeCliAdapter,
            "claude",
            _claude(),
            TokenCounts(10, 500, 30, 20),
        ),
        (
            CodexCliAdapter,
            "codex",
            _codex(),
            TokenCounts(100, 900, 0, 50),
        ),
    ],
    ids=["claude", "codex"],
)
@pytest.mark.parametrize("verified", [True, False])
def test_adapter_binds_usage_to_executed_cli_version(
    tmp_path,
    adapter_type,
    provider,
    turn_output,
    expected_tokens,
    verified,
):
    """Der gepinnte Bezugsstand ist kein Nachweis fuer die tatsaechlich
    ausgefuehrte CLI-Version (wu0.3/AC5). Bei unbekannter Version
    sind eine erklaerte Ablehnung VOR dem Turn oder ein PARTIAL-
    Beleg MIT erhaltenen Zaehlern erlaubt. Der bekannte Stand muss
    weiterhin einen gemessenen Turn erlauben.
    """
    version = (
        adapter_type.cli_version_pin
        if verified
        else "999.999.999"
    )
    executable, trace = write_usage_cli(
        tmp_path, provider, version, turn_output
    )

    request = replace(_request(), workdir=tmp_path)
    result = adapter_type(executable=str(executable)).send_turn(request)
    calls = trace.read_text().splitlines() if trace.exists() else []
    assert "version" in calls
    if not verified and "turn" not in calls:
        assert not result.ok
        assert result.error
        assert result.usage is None
        assert result.usage_event is None
        return

    assert calls.count("turn") == 1
    if verified:
        assert result.ok
    event = result.usage_event
    assert event is not None
    assert event.cli_version == version
    assert event.provider == provider
    assert event.session_id == request.session_id
    assert event.counter_scope is CounterScope.CALL_TOTAL
    assert event.status is (
        UsageStatus.MEASURED if verified else UsageStatus.PARTIAL
    )
    assert event.tokens == expected_tokens
    assert result.usage is not None


def test_codex_failure_without_usage_does_not_invent_zero_counts():
    result = codex_result(
        _result(json.dumps({
            "type": "turn.failed",
            "error": {"message": "quota"},
        })),
        session_id="session",
        cli_version=CodexCliAdapter.cli_version_pin,
    )
    assert not result.ok
    assert result.usage is None
    event = result.usage_event
    assert event is None or (
        event.status in (
            UsageStatus.UNAVAILABLE,
            UsageStatus.UNSUPPORTED,
        )
        and event.tokens is None
    )


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        "{}",
        '{"type":"turn.failed","error":{"message":"quota"}}',
    ],
)
def test_codex_missing_or_failed_turn_never_passes(text):
    assert not codex_result(_result(text)).ok


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_turns": 0},
        {"max_turns": True},
        {"max_budget_usd": float("nan")},
        {"timeout_s": float("inf")},
        {"max_context_tokens": -1},
        {"max_usage_delta_percentage_points": 0},
        {"max_usage_delta_percentage_points": 101},
        {"max_usage_delta_percentage_points": float("nan")},
    ],
)
def test_invalid_budgets_rejected(kwargs):
    with pytest.raises(ValueError):
        TurnBudget(**kwargs)


def test_valid_usage_delta_budget_accepted():
    assert TurnBudget(
        max_usage_delta_percentage_points=100.0
    ).max_usage_delta_percentage_points == 100.0


def test_codex_quota_shares_the_session_search_and_id_rules(tmp_path):
    for bad in ("../x", "a*", "a?", "", "a/b"):
        with pytest.raises(ValueError, match="ungueltig"):
            codex_quota(bad, tmp_path)
    _rollout(tmp_path, "thread-1", used_percent=1, resets_at=10)
    _rollout_path(tmp_path, "thread-1").parent.joinpath(
        "rollout-2026-09-17T09-10-36-thread-1.jsonl"
    ).write_text("")
    with pytest.raises(ValueError, match="mehrdeutig"):
        codex_quota("thread-1", tmp_path, now=0)
