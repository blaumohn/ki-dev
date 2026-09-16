"""Strukturierte CLI-Ergebnisse fuer begrenzte Loop-Aufrufe."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

from .contract import TurnResult, TurnStatus


def claude_result(result: TurnResult) -> TurnResult:
    """Budget- und Berechtigungsabbrueche trotz Exitcode 0 erkennen."""
    if not result.stdout.strip():
        return missing_result(result)
    try:
        value = json.loads(result.stdout)
        if not isinstance(value, dict) or value.get("type") != "result":
            raise ValueError("Claude-result fehlt")
        text = value.get("result", "")
        if not isinstance(text, str):
            raise ValueError("Claude-result ist kein Text")
        failed = (
            not result.ok
            or value.get("is_error") is not False
            or value.get("subtype") != "success"
            or bool(value.get("permission_denials"))
        )
        if failed:
            try:
                usage = _claude_usage(value)
            except (ValueError, TypeError):
                usage = None
            detail = json.dumps(
                {
                    "subtype": value.get("subtype"),
                    "result": text,
                    "errors": value.get("errors"),
                    "permission_denials": bool(
                        value.get("permission_denials")
                    ),
                },
                ensure_ascii=False,
            )
            return replace(
                result,
                status=TurnStatus.NONZERO_EXIT,
                stdout=text,
                usage=usage,
                error=detail[:2000],
            )
        return replace(result, stdout=text, usage=_claude_usage(value))
    except (ValueError, TypeError) as exc:
        return missing_result(result, str(exc))


def codex_result(result: TurnResult) -> TurnResult:
    """JSONL trennt Agentenantwort, Verbrauch und Turn-Fehler."""
    try:
        events = [
            json.loads(line) for line in result.stdout.splitlines()
        ]
        if any(not isinstance(event, dict) for event in events):
            raise ValueError("Codex-Ereignis ist kein Objekt")
        completed = [
            e for e in events if e.get("type") == "turn.completed"
        ]
        failures = [
            e
            for e in events
            if e.get("type") in ("error", "turn.failed")
        ]
        if failures or not result.ok:
            return replace(
                result,
                status=TurnStatus.NONZERO_EXIT,
                error=(
                    json.dumps(failures, ensure_ascii=False)
                    if failures
                    else result.error or result.stderr
                )[:2000],
            )
        if len(completed) != 1:
            raise ValueError(
                "genau ein Codex-turn.completed erforderlich"
            )
        source = completed[0]["usage"]
        if not isinstance(source, dict):
            raise ValueError("Codex-usage ist kein Objekt")
        input_tokens = _count(source, "input_tokens")
        cached = _count(source, "cached_input_tokens")
        if cached > input_tokens:
            raise ValueError("Cache-Tokens groesser als Input")
        usage = {
            "input_tokens": input_tokens - cached,
            "cache_read_input_tokens": cached,
            "cache_creation_input_tokens": 0,
            "output_tokens": _count(source, "output_tokens"),
        }
        messages = []
        for event in events:
            if event.get("type") == "item.completed":
                item = event.get("item", {})
                if not isinstance(item, dict):
                    raise ValueError("Codex-item ist kein Objekt")
                if item.get("type") == "agent_message":
                    text = item.get("text")
                    if not isinstance(text, str):
                        raise ValueError(
                            "Codex-Agentenantwort ist kein Text"
                        )
                    messages.append(text)
        if not messages:
            raise ValueError("Codex-Agentenantwort fehlt")
        return replace(result, stdout=messages[-1], usage=usage)
    except (ValueError, TypeError, KeyError) as exc:
        return missing_result(result, str(exc))


def claude_context_tokens(session_id: str, root: Path) -> int:
    """Letzten realen Request ohne synthetische Nullusage lesen."""
    if Path(session_id).name != session_id or not session_id:
        raise ValueError("ungueltige Claude-session_id")
    paths = list(root.glob(f"*/{session_id}.jsonl"))
    if len(paths) != 1:
        raise ValueError(
            "Claude-Sitzungsverbrauch fehlt oder ist mehrdeutig"
        )
    latest = None
    with paths[0].open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(
                    "Claude-Sitzungseintrag ist kein Objekt"
                )
            message = row.get("message", {})
            if not isinstance(message, dict):
                raise ValueError(
                    "Claude-Sitzungsnachricht ist kein Objekt"
                )
            if (
                row.get("type") == "assistant"
                and message.get("model") != "<synthetic>"
                and message.get("usage") is not None
            ):
                source = message["usage"]
                if not isinstance(source, dict):
                    raise ValueError(
                        "Claude-Sitzungsverbrauch ungueltig"
                    )
                latest = sum(
                    _count(source, key)
                    for key in (
                        "input_tokens",
                        "cache_read_input_tokens",
                        "cache_creation_input_tokens",
                    )
                )
    if latest is None:
        raise ValueError("Claude-Sitzung hat keinen Verbrauchsnachweis")
    return latest


def missing_result(result: TurnResult, detail: str = "") -> TurnResult:
    if not result.ok:
        return replace(
            result,
            error="; ".join(
                filter(
                    None,
                    (
                        result.error,
                        result.stderr[:2000],
                        result.stdout[:2000],
                        detail,
                    ),
                )
            ),
        )
    return replace(
        result,
        status=TurnStatus.NONZERO_EXIT,
        error=f"Verbrauchsnachweis fehlt/ungueltig: {detail}",
    )


def _claude_usage(value: dict) -> dict[str, int | float]:
    source = value.get("usage")
    if not isinstance(source, dict):
        raise ValueError("Claude-usage fehlt")
    usage = {
        key: _count(source, key)
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
        )
    }
    usage["num_turns"] = _count(value, "num_turns")
    cost = value.get("total_cost_usd")
    if (
        type(cost) not in (float, int)
        or not math.isfinite(cost)
        or cost < 0
    ):
        raise ValueError("Claude-total_cost_usd fehlt/ungueltig")
    usage["cost_usd"] = cost
    return usage


def _count(value: dict, key: str) -> int:
    count = value.get(key)
    if type(count) is not int or count < 0:
        raise ValueError(f"{key} fehlt/ungueltig")
    return count
