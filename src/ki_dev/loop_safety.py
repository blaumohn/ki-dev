"""Dauerhafte Bilanz und Grenzen fuer kostenpflichtige Aufrufe."""

from __future__ import annotations

import fcntl
import math
from dataclasses import dataclass, fields
from pathlib import Path

from ki_dev.executors.contract import TurnResult, TurnStatus
from ki_dev.run_store import RunStore, RunStoreError


@dataclass(frozen=True)
class SafetyLimits:
    max_agent_calls: int = 6
    max_total_tokens: int = 1_000_000
    max_claude_cost_usd: float = 3.0
    max_failed_corrections: int = 2

    def __post_init__(self) -> None:
        for name in (
            "max_agent_calls",
            "max_total_tokens",
            "max_failed_corrections",
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
    ) -> None:
        limits = self.limits()
        directory = self.store.run_dir / "calls"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._reserve(call_id, operation, metered, limits, provider)

    def _reserve(
        self,
        call_id: str,
        operation: str,
        metered: bool,
        limits: SafetyLimits,
        provider: str | None,
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
        self._write(
            call_id,
            "result",
            {
                "status": result.status.value if result else "local",
                "duration_s": result.duration_s if result else None,
                "usage": result.usage if result else None,
                "error": error or (result.error if result else None),
            },
        )

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
