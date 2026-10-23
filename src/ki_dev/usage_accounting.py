"""Pure projection of CallLedger evidence; never a second safety
ledger.

Only normalized counters and bounded provenance are persisted. A
call owns its cost once; request detail reconciles that cost instead
of adding to it.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, replace
from enum import StrEnum

from ki_dev.usage import CounterScope, UsageEvent, UsageStatus

CATEGORIES = ("fresh_input", "cache_read", "cache_creation", "output")
LEGACY_CATEGORIES = (
    "input_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "output_tokens",
)

# CallLedger.reserve() erhaelt den Executor-Adapternamen
# (``Executor.name``, z. B. "codex-cli"), waehrend usage.py-
# Normalisierer die Anbieterfamilie fuehren (z. B. "codex" -- ein
# potenzieller kuenftiger Codex App Server waere derselbe Anbieter,
# ein anderer Executor). Ohne diese Abbildung schlaegt der
# provider_mismatch-Vergleich fuer jeden gueltigen Beleg fehl und
# sperrt jede weitere Reservierung dauerhaft.
PROVIDER_FAMILY_BY_EXECUTOR = {
    "codex-cli": "codex",
    "claude-cli": "claude",
}


def _provider_family(executor_name: str | None) -> str | None:
    if executor_name is None:
        return None
    return PROVIDER_FAMILY_BY_EXECUTOR.get(executor_name, executor_name)


class UsagePurpose(StrEnum):
    ESTIMATION = "estimation"
    IMPLEMENTATION = "implementation"
    REVIEW = "review"
    REPAIR = "repair"
    HANDOFF = "handoff"


def metadata(value: str | None) -> str | None:
    if value is not None and (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 512
        or any(ord(char) < 32 for char in value)
    ):
        raise ValueError(
            "usage metadata must be a nonempty string <= 512 characters"
        )
    return value


@dataclass(frozen=True)
class UsageAttribution:
    bead_id: str | None
    task_revision: str | None
    family_id: str | None
    family_revision: str | None
    role: str
    purpose: UsagePurpose
    session_id: str | None = None
    parent_bead_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.purpose, UsagePurpose):
            raise ValueError("invalid usage purpose")
        for value in asdict(self).values():
            metadata(value)
        if not self.role:
            raise ValueError("usage role is required")

    @property
    def complete(self) -> bool:
        return all((
            self.bead_id,
            self.task_revision,
            self.family_id,
            self.family_revision,
            self.session_id,
        ))


def project_event(event: UsageEvent) -> dict:
    # detail is deliberately omitted: diagnostics must not persist
    # raw text.
    result = {
        key: metadata(getattr(event, key))
        for key in (
            "provider",
            "source",
            "schema_version",
            "cli_version",
            "requested_model",
            "confirmed_model",
            "session_id",
            "request_id",
        )
    }
    for key in ("event_time", "observed_at"):
        value = getattr(event, key)
        if value is not None and (
            type(value) not in (float, int) or not math.isfinite(value)
        ):
            raise ValueError("invalid usage timestamp")
        result[key] = value
    result.update(
        status=event.status.value,
        counter_scope=event.counter_scope.value,
        tokens=asdict(event.tokens) if event.tokens else None,
    )
    return result


def observation(
    event: UsageEvent,
    evidence_ref: str,
    *,
    summary: bool = False,
    baseline: UsageEvent | None = None,
) -> dict:
    metadata(evidence_ref)
    if not evidence_ref:
        raise ValueError("usage evidence reference is required")
    if (
        baseline is not None
        and event.counter_scope != CounterScope.CUMULATIVE_SESSION
    ):
        raise ValueError("baseline requires a cumulative counter")
    return {
        "schema_version": 1,
        "event": project_event(event),
        "evidence_ref": evidence_ref,
        "summary": summary,
        "baseline": project_event(baseline) if baseline else None,
    }


def counters(record: dict) -> tuple[dict[str, int] | None, list[str]]:
    event = record["event"]
    gaps = []
    if event["status"] != UsageStatus.MEASURED:
        gaps.append("measurement_incomplete")
    value = event["tokens"]
    if value is None:
        return None, gaps
    value = {key: value[key] for key in CATEGORIES}
    if event["counter_scope"] == CounterScope.CUMULATIVE_SESSION:
        base = record["baseline"]
        if (
            base is None
            or base["status"] != UsageStatus.MEASURED
            or base["counter_scope"] != CounterScope.CUMULATIVE_SESSION
            or not event["session_id"]
            or base["session_id"] != event["session_id"]
            or base["provider"] != event["provider"]
            or base["event_time"] is None
            or event["event_time"] is None
            or base["event_time"] >= event["event_time"]
        ):
            return None, gaps + ["counter_baseline_unknown"]
        value = {
            key: value[key] - base["tokens"][key] for key in CATEGORIES
        }
        if min(value.values()) < 0:
            return None, gaps + ["counter_reset"]
    return value, gaps


def started(result: dict | None) -> bool:
    """Ob der Prozess eines Aufrufs gestartet wurde. Nur ein
    ausdrückliches ``started: false`` belegt, dass kein Verbrauch
    entstand; ältere Ergebnisse ohne das Feld gelten als gestartet."""
    return result is None or result.get("started", True) is not False


@dataclass(frozen=True)
class CallUsage:
    run_id: str
    call_id: str
    attribution: UsageAttribution | None
    counts: dict[str, int]
    cost_usd: float
    status: str | None
    gaps: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    reconciliation: str
    difference: dict[str, int] | None

    @property
    def total(self) -> int:
        return sum(self.counts.values())


@dataclass(frozen=True)
class UsageReport:
    calls: tuple[CallUsage, ...]

    @property
    def total(self) -> int:
        return sum(call.total for call in self.calls)

    @property
    def complete(self) -> bool:
        return all(not call.gaps for call in self.calls)

    @property
    def by_purpose(self) -> dict[str, int]:
        result = {}
        for call in self.calls:
            key = (
                call.attribution.purpose.value
                if call.attribution
                else "unattributed"
            )
            result[key] = result.get(key, 0) + call.total
        return result


def _with_created_session(
    attribution: UsageAttribution | None, records: list[dict]
) -> UsageAttribution | None:
    """Ein Aufruf, der seine Sitzung erst anlegt, reserviert ohne
    ``session_id``; ihre ID nennt dann sein Verbrauchsbeleg. Nennen
    die Belege mehr als eine Sitzung, bleibt sie offen
    (``session_mismatch``).
    """
    sessions = {record["event"]["session_id"] for record in records}
    if attribution is None or attribution.session_id is not None:
        return attribution
    if len(sessions) != 1:
        return attribution
    return replace(attribution, session_id=sessions.pop())


def reconcile_call(
    run_id: str,
    call_id: str,
    start: dict | None,
    result: dict | None,
    records: list[dict],
    attribution: UsageAttribution | None,
) -> CallUsage:
    gaps = []
    if start is None:
        # Ergebnisnachweis ohne Startdatei (z. B. Altdaten): bekannter
        # Verbrauch bleibt sichtbar, aber als Luecke ausgewiesen statt
        # stillschweigend ausgelassen zu werden.
        gaps.append("start_missing")
        metered = True
        start_provider = None
    else:
        metered = start["metered"]
        start_provider = _provider_family(start.get("provider"))
    attribution = _with_created_session(attribution, records)
    if attribution is None or not attribution.complete:
        gaps.append("attribution_missing")
    if result is None or (
        metered and result.get("usage") is None and started(result)
    ):
        gaps.append("external_effect_unknown")
    requests = {}
    summaries = []
    refs = set()
    for record in records:
        event = record["event"]
        refs.add(record["evidence_ref"])
        value, problems = counters(record)
        gaps.extend(problems)
        if (
            attribution
            and attribution.session_id != event["session_id"]
        ):
            gaps.append("session_mismatch")
        if start_provider and start_provider != event["provider"]:
            gaps.append("provider_mismatch")
        if value is None:
            continue
        if record["summary"]:
            summaries.append(value)
        else:
            if not event["session_id"] or not event["request_id"]:
                gaps.append("request_identity_missing")
                continue
            key = (
                event["provider"],
                event["session_id"],
                event["request_id"],
            )
            if key in requests and requests[key] != value:
                gaps.append("request_conflict")
                # Keep the known lower bound, not two charges for one
                # request.
                value = {
                    k: max(value[k], requests[key][k])
                    for k in CATEGORIES
                }
            requests[key] = value
    usage = result.get("usage") if result else None
    if usage is not None:
        summaries.append(
            dict(
                zip(
                    CATEGORIES,
                    (usage[k] for k in LEGACY_CATEGORIES),
                    strict=True,
                )
            )
        )
    detail = {
        k: sum(v[k] for v in requests.values()) for k in CATEGORIES
    }
    total = {
        k: max((v[k] for v in summaries), default=0) for k in CATEGORIES
    }
    if summaries and any(v != summaries[0] for v in summaries):
        gaps.append("summary_conflict")
    difference = None
    reconciliation = "unknown"
    if summaries:
        reconciliation = "summary_only"
        if requests:
            difference = {
                k: total[k] - detail[k] for k in CATEGORIES
            }
            reconciliation = (
                "matched"
                if not any(difference.values())
                else "mismatch"
            )
            if reconciliation == "mismatch":
                gaps.append("reconciliation_gap")
        total = {k: max(total[k], detail[k]) for k in CATEGORIES}
    elif requests:
        total = detail
        reconciliation = "requests_only"
        gaps.append("summary_missing")
    elif metered and started(result):
        gaps.append("measurement_missing")
    return CallUsage(
        run_id,
        call_id,
        attribution,
        total,
        usage.get("cost_usd", 0.0) if usage else 0.0,
        result.get("status") if result else None,
        tuple(sorted(set(gaps))),
        tuple(sorted(refs)),
        reconciliation,
        difference,
    )
