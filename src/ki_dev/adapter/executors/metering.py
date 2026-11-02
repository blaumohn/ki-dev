"""Strukturierte CLI-Ergebnisse fuer begrenzte Agentenaufrufe."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from pathlib import Path

from ki_dev.usage import (
    normalize_claude_cli_result,
    normalize_codex_turn_usage,
)

from .claude_sessions import find_claude_sessions
from .contract import TurnResult, TurnStatus


def claude_result(
    result: TurnResult,
    *,
    session_id: str | None = None,
    cli_version: str | None = None,
) -> TurnResult:
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
            detail = _claude_failure(value, text)
            return replace(
                result,
                status=TurnStatus.NONZERO_EXIT,
                stdout=text,
                usage=usage,
                usage_event=_claude_usage_event(
                    usage, session_id, cli_version
                ),
                error=detail[:2000],
            )
        usage = _claude_usage(value)
        return replace(
            result,
            stdout=_claude_answer(value, text),
            usage=usage,
            usage_event=_claude_usage_event(
                usage, session_id, cli_version
            ),
        )
    except (ValueError, TypeError) as exc:
        return missing_result(result, str(exc))


def _claude_failure(value: dict, text: str) -> str:
    """Grund eines Abbruchs zum Lesen: die Meldung der CLI zuerst, sie
    steht auch im gekürzten Verlauf."""
    parts = [text] if text else []
    if value.get("subtype") != "success":
        parts.append(f"subtype={value.get('subtype')}")
    if value.get("errors"):
        errors = json.dumps(value["errors"], ensure_ascii=False)
        parts.append(f"errors={errors}")
    if value.get("permission_denials"):
        parts.append("Berechtigung verweigert")
    return "; ".join(parts) or "Claude meldet Fehler ohne Text"


def _claude_answer(value: dict, text: str) -> str:
    """Mit ``--json-schema`` steht die Antwort als Objekt in
    ``structured_output``; ``result`` ist dort nur Text des Modells."""
    structured = value.get("structured_output")
    if structured is None:
        return text
    return json.dumps(structured, ensure_ascii=False)


def claude_stream(
    stdout: str,
) -> tuple[str, tuple[float, int] | None]:
    """Zerlegt ``--output-format stream-json --verbose``.

    Liefert die rohe ``result``-Zeile (fuer ``claude_result``) und den
    5h-Kontingentwert aus dem letzten ``rate_limit_event`` als
    ``(used_percent, resets_at)``. ``utilization`` ist ein Anteil
    (0..1), beobachtet mit Claude Code 2.1.272. Ohne ``result``-Zeile
    bleibt ``stdout`` unveraendert, damit ``claude_result`` den
    Fehler meldet.
    """
    result_line = stdout
    quota = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "result":
            result_line = line
        elif event.get("type") == "rate_limit_event":
            quota = _claude_five_hour(event) or quota
    return result_line, quota


def _claude_five_hour(event: dict) -> tuple[float, int] | None:
    window = event.get("rate_limit_info")
    for key in ("unifiedWindows", "five_hour"):
        if not isinstance(window, dict):
            return None
        window = window.get(key)
    if not isinstance(window, dict):
        return None
    share = window.get("utilization")
    resets_at = window.get("resetsAt")
    if (
        type(share) not in (int, float)
        or not math.isfinite(share)
        or share < 0
        or type(resets_at) is not int
    ):
        return None
    return float(share) * 100, resets_at


def _claude_usage_event(
    usage, session_id: str | None, cli_version: str | None
):
    if usage is None:
        return None
    return normalize_claude_cli_result(
        usage, cli_version=cli_version, session_id=session_id
    )


def codex_result(
    result: TurnResult,
    *,
    session_id: str | None = None,
    cli_version: str | None = None,
) -> TurnResult:
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
            return _codex_failure_result(
                result, completed, failures, session_id, cli_version
            )
        if len(completed) != 1:
            raise ValueError(
                "genau ein Codex-turn.completed erforderlich"
            )
        source = completed[0]["usage"]
        if not isinstance(source, dict):
            raise ValueError("Codex-usage ist kein Objekt")
        usage = _codex_usage_from_source(source)
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
        return replace(
            result,
            stdout=messages[-1],
            usage=usage,
            usage_event=_codex_usage_event(
                source, session_id, cli_version
            ),
        )
    except (ValueError, TypeError, KeyError) as exc:
        return missing_result(result, str(exc))


def _codex_usage_from_source(source: dict) -> dict[str, int]:
    input_tokens = _count(source, "input_tokens")
    cached = _count(source, "cached_input_tokens")
    if cached > input_tokens:
        raise ValueError("Cache-Tokens groesser als Input")
    return {
        "input_tokens": input_tokens - cached,
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": 0,
        "output_tokens": _count(source, "output_tokens"),
    }


def _codex_failure_result(
    result: TurnResult,
    completed: list[dict],
    failures: list[dict],
    session_id: str | None,
    cli_version: str | None,
) -> TurnResult:
    """Ein fehlgeschlagener Aufruf verwirft keinen bereits vorhandenen,
    gueltigen ``turn.completed``-Summenbeleg (R1, ki-dev-ablauf-wu0.3).
    Fehlt der Beleg oder ist er ungueltig, bleibt ``usage``/
    ``usage_event`` ``None`` statt eines erfundenen Nullverbrauchs.

    ``status`` bleibt der urspruengliche Nicht-Erfolgsstatus (z. B.
    ``TIMEOUT``/``START_ERROR`` eines real abgebrochenen Prozesses)
    und wird nur bei ``OK`` auf ``NONZERO_EXIT`` herabgestuft (Exitcode
    0, aber inhaltlicher Fehler/`failures` in der JSONL) -- sonst
    wuerde ein Timeout stillschweigend als Nicht-Null-Exit erscheinen,
    entgegen der eigenen ``TurnStatus``-Vertragsaussage ("bewusst
    disjunkt", siehe ``contract.py``; Review-Nachtrag 2026-09-18
    12:50, ki-dev-ablauf-wu0.3)."""
    status = (
        TurnStatus.NONZERO_EXIT
        if result.status is TurnStatus.OK
        else result.status
    )
    usage = None
    usage_event = None
    usage_note = None
    if len(completed) == 1:
        source = completed[0].get("usage")
        if isinstance(source, dict):
            try:
                usage = _codex_usage_from_source(source)
            except ValueError as exc:
                usage_note = f"; turn.completed-usage ungueltig: {exc}"
            else:
                usage_event = _codex_usage_event(
                    source, session_id, cli_version
                )
    error = (
        json.dumps(failures, ensure_ascii=False)
        if failures
        else result.error or result.stderr
    )[:2000]
    return replace(
        result,
        status=status,
        usage=usage,
        usage_event=usage_event,
        error=error + (usage_note or ""),
    )


def _codex_usage_event(
    source, session_id: str | None, cli_version: str | None
):
    # Bewusst die rohe, noch nicht um Cache bereinigte Quelle -- der
    # Messvertrag erwartet Codex' Rohfeldschema (``input_tokens``
    # inkl. Cache), nicht das hiesige, bereits umgerechnete
    # ``usage``-Schema.
    return normalize_codex_turn_usage(
        source, cli_version=cli_version, session_id=session_id
    )


def claude_context_tokens(session_id: str, root: Path) -> int:
    """Letzten realen Request ohne synthetische Nullusage lesen."""
    paths = find_claude_sessions(root, session_id)
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
