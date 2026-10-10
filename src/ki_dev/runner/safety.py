"""Dauerhafte Bilanz und Grenzen fuer kostenpflichtige Aufrufe."""

from __future__ import annotations

import fcntl
import json
import logging
import math
import os
import tempfile
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from ki_dev.adapter.executors.contract import TurnResult, TurnStatus
from ki_dev.flow.model import Verdict
from ki_dev.run_store import RunStore, RunStoreError
from ki_dev.usage import CounterScope, UsageEvent
from ki_dev.usage_accounting import (
    UsageAttribution,
    UsagePurpose,
    UsageReport,
    observation,
    reconcile_call,
)

# Fortschritt fuer ``ki-dev -f implement --verbose``.
_log = logging.getLogger("ki_dev.run")


@dataclass(frozen=True)
class SafetyLimits:
    """Laufweite Verbrauchsgrenzen.

    ``min_remaining_percent`` ist eine eigenstaendige, vom
    Aufgabenbudget unabhaengige Schutzreserve des Kontokontingents
    (Schwellenwert, nicht Messwert): sie haelt an, sobald fuer eine
    Rolle noch so wenig Fuenfstundenkontingent uebrig ist, unabhaengig
    davon, wie viel diese Aufgabe selbst schon verbraucht hat. Das
    davon getrennte Aufgaben-Delta-Budget lebt pro Rolle in
    ``TurnBudget.max_usage_delta_percentage_points``
    (ki-dev-ablauf-dqv).
    """

    max_agent_calls: int = 6
    max_total_tokens: int = 1_000_000
    max_claude_cost_usd: float = 3.0
    max_failed_corrections: int = 2
    max_stagnant_changes: int = 3
    min_remaining_percent: float = 10.0

    def __post_init__(self) -> None:
        for name in (
            "max_agent_calls",
            "max_total_tokens",
            "max_failed_corrections",
            "max_stagnant_changes",
        ):
            if (
                type(getattr(self, name)) is not int
                or getattr(self, name) < 1
            ):
                raise ValueError(
                    f"{name} muss eine positive Ganzzahl sein"
                )
        cost = self.max_claude_cost_usd
        if (
            type(cost) not in (int, float)
            or not math.isfinite(cost)
            or cost <= 0
        ):
            raise ValueError(
                "max_claude_cost_usd muss positiv und endlich sein"
            )
        remaining = self.min_remaining_percent
        if (
            type(remaining) not in (int, float)
            or not math.isfinite(remaining)
            or not (0 <= remaining < 100)
        ):
            raise ValueError(
                "min_remaining_percent muss in [0, 100) liegen"
            )


class SafetyStop(RuntimeError):
    """Die naechste kostenpflichtige Operation ist nicht freigegeben."""


class CallLedger:
    def __init__(self, store: RunStore) -> None:
        self.store = store

    def limits(self) -> SafetyLimits:
        config = self.store.load_manifest().get("safety_limits")
        if not isinstance(config, dict):
            raise SafetyStop(
                "Altlauf ohne Verbrauchsbilanz: kein automatischer "
                "Neustart; bisherigen Verbrauch und Grenzen klaeren"
            )
        if set(config) != {
            field.name for field in fields(SafetyLimits)
        }:
            raise SafetyStop(
                "Persistierte Verbrauchsgrenzen unvollstaendig"
            )
        try:
            return SafetyLimits(**config)
        except (TypeError, ValueError) as exc:
            raise SafetyStop(
                f"Ungueltige Verbrauchsgrenzen: {exc}"
            ) from exc

    def reserve(
        self,
        call_id: str,
        operation: str,
        metered: bool,
        provider: str | None = None,
        *,
        attribution: UsageAttribution | None = None,
    ) -> None:
        limits = self.limits()
        _log.info(
            "Aufruf %s startet (%s)", operation, provider or "lokal"
        )
        directory = self.store.run_dir / "calls"
        directory.mkdir(parents=True, exist_ok=True)
        with self.store.usage_lock():
            self._reserve(
                call_id,
                operation,
                metered,
                limits,
                provider,
                attribution,
            )

    def _reserve(
        self,
        call_id: str,
        operation: str,
        metered: bool,
        limits: SafetyLimits,
        provider: str | None,
        attribution: UsageAttribution | None,
    ) -> None:
        starts = sorted(
            (self.store.run_dir / "calls").glob("*-start.json")
        )
        if len(starts) >= limits.max_agent_calls:
            raise SafetyStop(f"Aufrufgrenze erreicht: {len(starts)}")
        tokens = 0
        cost = 0.0
        for path in starts:
            start = self.store._load_json(path)
            result_path = path.with_name(
                path.name.replace("-start.json", "-result.json")
            )
            if not result_path.exists():
                raise SafetyStop(
                    "Verbrauch eines begonnenen Aufrufs ist ungeklaert"
                )
            result = self.store._load_json(result_path)
            usage = result.get("usage")
            if start["metered"] and usage is None:
                raise SafetyStop(
                    "Verbrauch eines Agentenaufrufs unbekannt; "
                    "kein weiterer Aufruf ohne Abgleich"
                )
            if usage:
                validate_usage(usage)
                if (
                    start.get("provider") == "claude-cli"
                    and "cost_usd" not in usage
                ):
                    raise SafetyStop("Claude-Kostennachweis fehlt")
                tokens += sum(
                    usage.get(key, 0)
                    for key in (
                        "input_tokens",
                        "output_tokens",
                        "cache_read_input_tokens",
                        "cache_creation_input_tokens",
                    )
                )
                cost += usage.get("cost_usd", 0.0)
        report = self._usage_report()
        for call in report.calls:
            # attribution_missing/start_missing sind fehlende
            # Provenienz, keine widerspruechliche Bilanz -- sie
            # bleiben im Bericht sichtbar, sperren aber keine
            # weitere Reservierung.
            blocking = set(call.gaps) - {
                "attribution_missing",
                "start_missing",
            }
            if blocking:
                raise SafetyStop(
                    "Verbrauchsabgleich unvollstaendig: "
                    + ", ".join(sorted(blocking))
                )
        tokens = report.total
        if tokens >= limits.max_total_tokens:
            raise SafetyStop(f"Token-Grenze erreicht: {tokens}")
        if cost >= limits.max_claude_cost_usd:
            raise SafetyStop(
                f"Claude-Kostengrenze erreicht: {cost:g} USD"
            )
        self._write(
            call_id,
            "start",
            {
                "operation": operation,
                "metered": metered,
                "provider": provider,
                "attribution": (
                    asdict(attribution) if attribution else None
                ),
            },
        )

    def finish(
        self,
        call_id: str,
        result: TurnResult | None,
        error: str | None,
    ) -> None:
        if result is not None and result.usage is not None:
            validate_usage(result.usage)
        if result is not None:
            usage = result.usage or {}
            _log.info(
                "Aufruf %s: %s, %.0f s, Runden %s, %s USD%s",
                call_id.split("-")[1],
                result.status.value,
                result.duration_s,
                usage.get("num_turns", "?"),
                usage.get("cost_usd", "?"),
                f", {(error or result.error)[:200]}"
                if error or result.error
                else "",
            )
        with self.store.usage_lock():
            self._write(call_id, "result", {
                "status": result.status.value if result else "local",
                "duration_s": result.duration_s if result else None,
                "usage": result.usage if result else None,
                "error": error or (result.error if result else None),
            })

    def record_usage(
        self,
        call_id: str,
        event: UsageEvent,
        evidence_ref: str,
        *,
        summary: bool = False,
        baseline: UsageEvent | None = None,
    ) -> None:
        """Attach compact evidence without resolving an unknown
        external effect.

        Cumulative counters require an explicit, same-session
        baseline and describe the whole call interval; they are
        never individual requests.
        """
        if (
            event.counter_scope == CounterScope.CUMULATIVE_SESSION
            and not summary
        ):
            raise ValueError(
                "cumulative counters must be call summaries"
            )
        value = observation(
            event, evidence_ref, summary=summary, baseline=baseline
        )
        with self.store.usage_lock():
            if (
                not call_id
                or Path(call_id).name != call_id
                or call_id in {".", ".."}
            ):
                raise RunStoreError("ungueltiger Aufrufbezug")
            self.store._load_json(
                self.store.run_dir / "calls" / f"{call_id}-start.json"
            )
            # Request identity belongs to exactly one call, even
            # across runs. Paths and observation times are
            # provenance, not identity.
            for path in self.store.root.glob("*/usage/*/*.json"):
                same_call = (
                    path.parent.name == call_id
                    and path.parents[2] == self.store.run_dir
                )
                if same_call:
                    continue
                old = self.store._load_json(path)
                other = old["event"]
                if (event.provider, event.session_id) != (
                    other["provider"],
                    other["session_id"],
                ):
                    continue
                if evidence_ref == old["evidence_ref"]:
                    raise SafetyStop(
                        "Verbrauchsbeleg bereits einem anderen "
                        "Aufruf zugeordnet"
                    )
                if (
                    not summary
                    and not old["summary"]
                    and event.request_id
                    and event.request_id == other["request_id"]
                ):
                    raise SafetyStop(
                        "Request bereits einem anderen Aufruf "
                        "zugeordnet"
                    )
                if (
                    baseline
                    and old["baseline"]
                    and event.event_time is not None
                    and baseline.event_time is not None
                    and other["event_time"] is not None
                    and old["baseline"]["event_time"] is not None
                    and max(
                        baseline.event_time,
                        old["baseline"]["event_time"],
                    )
                    < min(event.event_time, other["event_time"])
                ):
                    raise SafetyStop(
                        "Ueberlappende kumulative Aufrufintervalle"
                    )
            self.store.write_usage(call_id, value)

    def usage_report(
        self,
        *,
        family_id: str | None = None,
        family_revision: str | None = None,
    ) -> UsageReport:
        """Read one consistent projection; family reports include all
        local runs."""
        with self.store.usage_lock():
            if family_id is None:
                return self._usage_report()
            calls = []
            for path in sorted(self.store.root.glob("*/calls")):
                other_store = RunStore(
                    self.store.root, path.parent.name
                )
                report = CallLedger(other_store)._usage_report()
                calls.extend(
                    call
                    for call in report.calls
                    if call.attribution
                    and call.attribution.family_id == family_id
                    and (
                        family_revision is None
                        or call.attribution.family_revision
                        == family_revision
                    )
                )
            return UsageReport(tuple(calls))

    def _usage_report(self) -> UsageReport:
        calls_dir = self.store.run_dir / "calls"
        start_ids = {
            path.name.removesuffix("-start.json")
            for path in calls_dir.glob("*-start.json")
        }
        # Ergebnisnachweise ohne Startdatei (z. B. Altdaten aus vor der
        # Reservierungspflicht) bleiben sichtbar statt stillschweigend
        # ausgelassen zu werden (reconcile_call markiert sie als
        # start_missing statt sie als gemessen auszugeben).
        result_ids = {
            path.name.removesuffix("-result.json")
            for path in calls_dir.glob("*-result.json")
        }
        calls = []
        for call_id in sorted(start_ids | result_ids):
            start_path = calls_dir / f"{call_id}-start.json"
            start = (
                self.store._load_json(start_path)
                if start_path.exists()
                else None
            )
            result_path = calls_dir / f"{call_id}-result.json"
            result = (
                self.store._load_json(result_path)
                if result_path.exists()
                else None
            )
            if result and result.get("usage") is not None:
                validate_usage(result["usage"])
            binding = start.get("attribution") if start else None
            attribution = (
                UsageAttribution(
                    **{
                        **binding,
                        "purpose": UsagePurpose(binding["purpose"]),
                    }
                )
                if binding
                else None
            )
            calls.append(
                reconcile_call(
                    self.store.run_id,
                    call_id,
                    start,
                    result,
                    self.store.load_usage(call_id),
                    attribution,
                )
            )
        return UsageReport(tuple(calls))

    def reconcile(self, call_id: str, artifact: object) -> None:
        start = self.store._load_json(
            self.store.run_dir / "calls" / f"{call_id}-start.json"
        )
        if not start["metered"]:
            self.finish(call_id, None, None)
            return
        usage = (
            artifact.get("usage")
            if isinstance(artifact, dict)
            else None
        )
        validate_usage(usage)
        if (
            start.get("provider") == "claude-cli"
            and "cost_usd" not in usage
        ):
            raise SafetyStop("Claude-Abgleich braucht cost_usd")
        self.finish(
            call_id,
            TurnResult(
                TurnStatus.OK,
                None,
                "",
                "",
                (),
                0.0,
                usage=usage,
            ),
            None,
        )

    def _write(self, call_id: str, suffix: str, value: object) -> None:
        if not call_id or Path(call_id).name != call_id:
            raise RunStoreError("ungueltiger Aufrufbezug")
        path = self.store.run_dir / "calls" / f"{call_id}-{suffix}.json"
        self.store._write_once(path, value)


class QuotaBaseline:
    """Rollengebundene Basislinie fuer das Aufgaben-Delta-Budget
    (ki-dev-ablauf-dqv).

    Anders als ``CallLedger`` ist dieser Zustand bewusst veraenderlich:
    eine neue Fensterrunde (anderes ``resets_at``) ersetzt die alte
    Basislinie, statt sie wie einen unveraenderlichen Nachweis
    abzulehnen -- das Kontingent hat sich real erneuert, ein neues
    Delta-Budget pro Fenster ist beabsichtigt, kein Bug. Die Datei
    liegt unter ``<run>/quota/<role>.json``, an ``run_dir`` und damit
    an genau diese Aufgabe gebunden (ein ``run_id`` steht durchgehend
    fuer eine Aufgabe); sie ueberlebt Resume und Prozessneustart
    unveraendert, solange das Fenster dasselbe bleibt.
    """

    def __init__(self, store: RunStore) -> None:
        self.store = store

    def delta_percent(
        self, role: str, used_percent: float, resets_at: int
    ) -> float:
        """Beobachtetes kontoweites Wachstum seit Baseline dieser
        Rolle; setzt bei erster Messung oder einem echten
        Fensterrollover neu auf ``0`` zurueck. Konservatives
        Pausesignal, keine exakte Zurechnung: paralleler fremder
        Verbrauch auf demselben Konto zaehlt mit.

        Ein echter Rollover erhoeht ``resets_at`` immer (das naechste
        Fensterende liegt spaeter als das vorige); ein ``resets_at``
        *unter* der gespeicherten Basislinie ist kein legitimer neuer
        Fensterstand, sondern ein widerspruechlicher Messwert (z. B.
        eine veraltete, zwischenzeitlich ueberholte lokale Ablage).
        Ein solcher Widerspruch wird gemeldet, nicht als stiller Reset
        uebernommen (Leitlinie 'Fallbacks verdecken keine Fehler',
        ki-dev-ablauf-dqv-Nachreview)."""
        if not role or Path(role).name != role:
            raise ValueError("ungueltige Rollenbezeichnung")
        directory = self.store.run_dir / "quota"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{role}.json"
        with (directory / f".{role}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            baseline = self._read(path)
            if baseline is None or resets_at > baseline["resets_at"]:
                self._replace(
                    path,
                    {
                        "used_percent": used_percent,
                        "resets_at": resets_at,
                    },
                )
                return 0.0
            if resets_at == baseline["resets_at"]:
                return used_percent - baseline["used_percent"]
            raise RunStoreError(
                f"widerspruechliche Kontingent-Basislinie fuer "
                f"Rolle {role!r}: resets_at ging von "
                f"{baseline['resets_at']} auf {resets_at} zurueck"
            )

    def _read(self, path: Path) -> dict[str, object] | None:
        if not path.exists():
            return None
        baseline = self.store._load_json(path)
        if (
            not isinstance(baseline, dict)
            or type(baseline.get("used_percent")) not in (int, float)
            or type(baseline.get("resets_at")) is not int
        ):
            raise RunStoreError(
                f"ungueltige Kontingent-Basislinie: {path}"
            )
        return baseline

    @staticmethod
    def _replace(path: Path, value: dict[str, object]) -> None:
        encoded = json.dumps(value, sort_keys=True).encode() + b"\n"
        descriptor, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


def stagnation_reason(
    store: RunStore,
    *,
    verdict: str,
    requirement_ref: str | None,
    limit: int,
) -> str | None:
    """Erkenne eine ununterbrochene Folge von CHANGES an derselben
    Abnahmekriteriums-Referenz.

    Der Aufrufer persistiert die aktuelle Entscheidung immer VOR
    diesem Aufruf (siehe ``RunRuntime._accept_artifact``); ``verdict``
    und ``requirement_ref`` beschreiben also dieselbe Entscheidung, die
    bereits als juengste Nachricht in ``store.load_messages()`` steht.
    ``limit`` zaehlt deshalb inklusive dieser aktuellen Entscheidung:
    ``max_stagnant_changes=3`` haelt beim dritten CHANGES in Folge an
    derselben Referenz an, nicht erst beim vierten.

    Fortschritt bedeutet eine geloeste oder gewechselte Referenz, nicht
    dieselbe geaenderte Datei oder ein groesserer Diff: jede andere
    Urteil oder ein anderes ``requirement_ref`` unterbricht die Serie.
    Persistierte Nachrichten ueberleben Resume und Sitzungswechsel,
    daher wird die Serie nicht durch einen Neustart zurueckgesetzt.
    """
    if verdict != Verdict.CHANGES or not requirement_ref:
        return None
    streak = 0
    for message in reversed(store.load_messages()):
        if (
            message.get("verdict") != Verdict.CHANGES
            or message.get("requirement_ref") != requirement_ref
        ):
            break
        streak += 1
    if streak < limit:
        return None
    tokens, cost = recorded_usage(store)
    return (
        f"Stillstand: {requirement_ref} bleibt seit {streak} "
        "Korrekturrunden in Folge verletzt (bisheriger Verbrauch "
        f"{tokens} Tokens, {cost:g} USD); Ursache/Loesungsansatz vor "
        "weiterem Bau klaeren."
    )


def recorded_usage(store: RunStore) -> tuple[int, float]:
    """Bereits abgeschlossener Verbrauch als Beleg fuer eine Eskalation.

    Rein informativ: die verbindliche Freigabepruefung bleibt
    ``CallLedger._reserve``; hier zaehlt nur bereits abgeschlossener,
    gueltiger Verbrauch, ohne unvollstaendige Aufrufe zu beanstanden.
    """
    report = CallLedger(store).usage_report()
    return report.total, sum(call.cost_usd for call in report.calls)


def validate_usage(usage: object) -> None:
    if not isinstance(usage, dict):
        raise SafetyStop(
            "Abgleich braucht einen Verbrauchsnachweis (usage)"
        )
    for key in (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        value = usage.get(key)
        if type(value) is not int or value < 0:
            raise SafetyStop(f"Ungueltiger Verbrauch: {key}")
    if "cost_usd" in usage:
        value = usage["cost_usd"]
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or value < 0
        ):
            raise SafetyStop("Ungueltiger Verbrauch: cost_usd")
