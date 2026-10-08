"""Unabhaengige Abnahme fuer wu0.2 (Review von 2c69ddc).

Grundlage: docs/architecture/tokenmessung-estimatoren.de.md,
Abschnitt Messvertrag und sparsame Extraktion. Kumulative Snapshots
werden nicht addiert; Kategorien und enthaltene Unterkategorien behalten
ihre Bedeutung; Widersprueche und fehlende Belege bleiben sichtbar.

Nur synthetische Metadaten, keine Modellaufrufe. Die Erwartungswerte
folgen aus den Beispielen, nicht aus der Zustandsmaschine
oder dem bisherigen skalaren Testorakel. Rote Tests sind Abnahmeluecken;
kein xfail und keine Aenderung des Produktionscodes zum Gruenfaerben.
"""

import json

import pytest

from ki_dev.adapter.executors.codex_cli import CLI_VERSION
from ki_dev.usage import (
    CounterScope,
    UsageStatus,
    read_codex_rollout_usage,
)


def counts(input_tokens, output_tokens, cached=0, reasoning=0):
    """Counts include cache in input and reasoning in output."""
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached,
        "output_tokens": output_tokens,
        "reasoning_output_tokens": reasoning,
        "total_tokens": input_tokens + output_tokens,
    }


@pytest.mark.parametrize(
    "before,after",
    [
        (counts(100, 100), counts(90, 120)),
        (counts(100, 100), counts(120, 90)),
        (counts(100, 100, cached=50), counts(120, 110, cached=40)),
        (
            counts(100, 100, reasoning=50),
            counts(110, 120, reasoning=40),
        ),
    ],
    ids=["input", "output", "cache", "reasoning"],
)
def test_category_regression_remains_visible_despite_total_growth(
    tmp_path, before, after
):
    """A decreasing category contradicts an uninterrupted counter.

    Every individual snapshot is valid and the grand total grows. The
    cross-snapshot regression must still taint the cumulative result.
    This does not prescribe request attribution across a reset.
    """
    result = scan(
        tmp_path,
        [snapshot(before, minute=0), snapshot(after, minute=1)],
    )
    cumulative = [
        event
        for event in result.events
        if event.counter_scope is CounterScope.CUMULATIVE_SESSION
    ]
    assert len(cumulative) == 1
    assert cumulative[0].status is UsageStatus.PARTIAL
    assert cumulative[0].detail


@pytest.mark.parametrize("mode", ["initial", "growth", "untimed"])
@pytest.mark.parametrize(
    "available,reported_usage",
    [
        (counts(0, 11), counts(11, 0)),
        (counts(11, 0), counts(0, 11)),
        (counts(11, 0), counts(11, 0, cached=11)),
        (counts(0, 11), counts(0, 11, reasoning=11)),
    ],
    ids=["input", "output", "cache", "reasoning"],
)
def test_other_categories_cannot_cover_a_request(
    tmp_path, mode, available, reported_usage
):
    """Other categories cannot cover the requested eleven tokens.

    This applies to an initial/untimed total as well as a later delta.
    The baseline has no request; only the disputed reading remains;
    its reported amount must survive, with uncertainty and a diagnosis.
    """
    rows = []
    total = available
    if mode == "growth":
        baseline = counts(100, 100, cached=20, reasoning=20)
        rows.append(snapshot(baseline, minute=0))
        total = {
            key: baseline[key] + value
            for key, value in available.items()
        }
    rows.append(
        snapshot(
            total,
            reported_usage,
            minute=None if mode == "untimed" else 1,
        )
    )
    events = requests(scan(tmp_path, rows))
    assert len(events) == 1
    assert events[0].tokens.total == 11
    assert events[0].status is UsageStatus.PARTIAL
    assert events[0].detail


@pytest.mark.parametrize("copies", [2, 3, 5])
@pytest.mark.parametrize("timing", ["timed", "untimed", "mixed"])
def test_repeated_snapshot_does_not_create_measured_consumption(
    tmp_path, copies, timing
):
    """Repeated total=last=100 provides no new identity evidence.

    They cannot justify 200+ tokens. Deduplication or explicitly
    uncertain observations are both allowed; deleting all usage is not.
    Mixed timing also forbids counting the same evidence in both paths.
    """
    usage = counts(70, 30, cached=20, reasoning=10)
    rows = [
        snapshot(
            usage,
            usage,
            minute=index
            if timing == "timed" or (timing == "mixed" and index == 0)
            else None,
        )
        for index in range(copies)
    ]
    result = scan(tmp_path, rows)
    events = requests(result)
    assert events
    assert all(event.tokens.total == 100 for event in events)
    assert measured_total(result) <= 100
    assert all(
        event.status is UsageStatus.MEASURED
        or (event.status is UsageStatus.PARTIAL and event.detail)
        for event in events
    )


def test_removing_timestamps_cannot_increase_measured_consumption(
    tmp_path,
):
    """Losing timestamps cannot establish new requests."""
    usage = counts(70, 30, cached=20, reasoning=10)
    timed = scan(
        tmp_path, [snapshot(usage, usage, minute=i) for i in range(3)]
    )
    untimed = scan(tmp_path, [snapshot(usage, usage) for _ in range(3)])
    assert measured_total(timed) == 100
    assert requests(untimed)
    assert measured_total(untimed) <= measured_total(timed)


@pytest.mark.parametrize("reverse_rows", [False, True])
@pytest.mark.parametrize(
    "reported_usage",
    [
        counts(11, 0),
        counts(0, 11),
        counts(70, 30, cached=20, reasoning=10),
    ],
    ids=["input", "output", "mixed-with-subcategories"],
)
def test_equal_cost_requests_with_exact_category_growth_are_preserved(
    tmp_path, reported_usage, reverse_rows
):
    """Each ordered observation adds exactly one full request vector.

    Counter growth establishes three contributions even though their
    values match. Included cache/reasoning cannot inflate the totals.
    File order does not replace event time.
    """
    rows = [
        snapshot(
            {
                key: value * factor
                for key, value in reported_usage.items()
            },
            reported_usage,
            minute=factor,
        )
        for factor in (1, 2, 3)
    ]
    result = scan(tmp_path, rows[::-1] if reverse_rows else rows)
    events = requests(result)
    assert len(events) == 3
    assert all(event.status is UsageStatus.MEASURED for event in events)
    for event in events:
        assert (
            event.tokens.fresh_input
            == reported_usage["input_tokens"]
            - reported_usage["cached_input_tokens"]
        )
        assert (
            event.tokens.cache_read
            == reported_usage["cached_input_tokens"]
        )
        assert event.tokens.output == reported_usage["output_tokens"]
        assert (
            event.tokens.reasoning_output
            == reported_usage["reasoning_output_tokens"]
        )
    assert measured_total(result) == 3 * reported_usage["total_tokens"]


@pytest.mark.parametrize("covers_both", [False, True])
@pytest.mark.parametrize(
    "reported_usage,insufficient_delta",
    [
        (counts(11, 0), counts(11, 11)),
        (counts(0, 11), counts(11, 11)),
        (counts(11, 0, cached=11), counts(22, 0, cached=11)),
        (counts(0, 11, reasoning=11), counts(0, 22, reasoning=11)),
    ],
    ids=["fresh-input", "output", "cache", "reasoning"],
)
def test_joint_confirmation_requires_shared_category_coverage(
    tmp_path, reported_usage, insufficient_delta, covers_both
):
    """Two readings cannot spend the same category evidence twice.

    The baseline has no request. An unanchored reading is followed by
    an identical reading with a cumulative delta of 22 tokens. In the
    negative cases only one request fits the relevant category, even
    though the scalar delta equals twice the request total. Exactly
    one request is directly supported; the earlier reading may merge
    with it or remain PARTIAL with a diagnosis. It cannot be MEASURED
    as an additional request. All reported categories remain intact.

    Positive controls supply twice the complete request vector and
    require both requests to survive as MEASURED. Rejecting every
    pending reading would therefore not satisfy this contract.
    """
    baseline = counts(100, 100, cached=20, reasoning=20)
    delta = (
        {key: 2 * value for key, value in reported_usage.items()}
        if covers_both
        else insufficient_delta
    )
    total = {key: baseline[key] + value for key, value in delta.items()}
    pending = snapshot(None, reported_usage, minute=1)
    del pending["payload"]["info"]["total_token_usage"]
    result = scan(
        tmp_path,
        [
            snapshot(baseline, minute=0),
            pending,
            snapshot(total, reported_usage, minute=2),
        ],
    )
    events = requests(result)
    assert events
    for event in events:
        assert event.tokens.total == 11
        assert event.tokens.fresh_input == (
            reported_usage["input_tokens"]
            - reported_usage["cached_input_tokens"]
        )
        assert (
            event.tokens.cache_read
            == reported_usage["cached_input_tokens"]
        )
        assert event.tokens.output == reported_usage["output_tokens"]
        assert (
            event.tokens.reasoning_output
            == reported_usage["reasoning_output_tokens"]
        )
        assert event.status is UsageStatus.MEASURED or (
            event.status is UsageStatus.PARTIAL and event.detail
        )
    expected_requests = 2 if covers_both else 1
    assert measured_total(result) == 11 * expected_requests
    if covers_both:
        assert len(events) == 2


@pytest.mark.parametrize("mixed_timing", [False, True])
@pytest.mark.parametrize("compact_first", [False, True])
@pytest.mark.parametrize(
    "omit_total_in",
    [
        ("total_token_usage",),
        ("last_token_usage",),
        ("total_token_usage", "last_token_usage"),
    ],
    ids=["cumulative", "request", "both"],
)
def test_redundant_total_representation_is_not_new_identity(
    tmp_path, mixed_timing, compact_first, omit_total_in
):
    """Omitting redundant total_tokens cannot create a second request.

    Both observations have identical complete category counters. Their
    totals remain exactly derivable; no identity or consumption evidence
    was added. Each representation alone must retain its measurement.
    Together they still justify exactly 100 MEASURED tokens, regardless
    of representation order or one observation having a timestamp.
    Additional observations may be deduplicated or remain PARTIAL.
    """
    usage = counts(70, 30, cached=20, reasoning=10)
    full = snapshot(dict(usage), dict(usage))
    compact = snapshot(dict(usage), dict(usage))
    for name in omit_total_in:
        del compact["payload"]["info"][name]["total_tokens"]
    for row in (full, compact):
        assert measured_total(scan(tmp_path, [row])) == 100
    rows = [compact, full] if compact_first else [full, compact]
    if mixed_timing:
        rows[0]["timestamp"] = "2026-04-04T09:00:00.000Z"
    result = scan(tmp_path, rows)
    events = requests(result)
    assert events
    assert all(event.tokens.total == 100 for event in events)
    assert measured_total(result) == 100
    assert all(
        event.status is UsageStatus.MEASURED
        or (event.status is UsageStatus.PARTIAL and event.detail)
        for event in events
    )


def snapshot(total, last=None, minute=None):
    info = {"total_token_usage": total}
    if last is not None:
        info["last_token_usage"] = last
    row = {
        "type": "event_msg",
        "payload": {"type": "token_count", "info": info},
    }
    if minute is not None:
        row["timestamp"] = f"2026-04-04T09:{minute:02d}:00.000Z"
    return row


def scan(tmp_path, rows):
    path = tmp_path / "synthetic-review.jsonl"
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    return read_codex_rollout_usage(
        path, cli_version=CLI_VERSION
    )


def requests(result):
    return [
        event
        for event in result.events
        if event.counter_scope is CounterScope.PER_REQUEST
    ]


def measured_total(result):
    return sum(
        event.tokens.total
        for event in requests(result)
        if event.status is UsageStatus.MEASURED
    )
