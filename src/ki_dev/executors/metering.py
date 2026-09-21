"""Strukturierte CLI-Ergebnisse fuer begrenzte Loop-Aufrufe."""

from __future__ import annotations

import json
import math
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from .codex_sessions import find_session_rollout
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
                usage_event=_claude_usage_event(
                    usage, session_id, cli_version
                ),
                error=detail[:2000],
            )
        usage = _claude_usage(value)
        return replace(
            result,
            stdout=text,
            usage=usage,
            usage_event=_claude_usage_event(
                usage, session_id, cli_version
            ),
        )
    except (ValueError, TypeError) as exc:
        return missing_result(result, str(exc))


def _claude_usage_event(
    usage, session_id: str | None, cli_version: str | None
):
    if usage is None:
        return None
    # Lokaler Import: ``ki_dev.usage`` importiert ueber die Adapter
    # zurueck auf dieses Modul (Versionskonstanten); ein Modulimport
    # auf Dateiebene wuerde einen Ringimport schliessen.
    from ki_dev.usage import normalize_claude_cli_result

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
    # Lokaler Import: ``ki_dev.usage`` importiert ueber die Adapter
    # zurueck auf dieses Modul (Versionskonstanten); ein Modulimport
    # auf Dateiebene wuerde einen Ringimport schliessen. Bewusst die
    # rohe, noch nicht um Cache bereinigte Quelle -- der Messvertrag
    # erwartet Codex' Rohfeldschema (``input_tokens`` inkl. Cache),
    # nicht das hiesige, bereits umgerechnete ``usage``-Schema.
    from ki_dev.usage import normalize_codex_turn_usage

    return normalize_codex_turn_usage(
        source, cli_version=cli_version, session_id=session_id
    )


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


FIVE_HOUR_WINDOW_MINUTES = 300

# Betriebsvorgabe, keine Aktualitaetsgarantie: begrenzt nur, wie lange
# ein zuletzt bekannter Messwert noch als Naeherung gilt, bevor die
# Unsicherheit zu gross wird. Ein juengerer Wert kann trotzdem schon
# ueberholt sein, ein aelterer beweist mit Sicherheit nichts mehr.
MAX_MEASUREMENT_AGE_S = 1800

# Ein Ereignis-Zeitstempel spuerbar nach 'now' ist kein Uhrenversatz
# mehr, sondern ein unplausibler/widerspruechlicher Wert und wird
# abgelehnt statt als "besonders frisch" akzeptiert.
CLOCK_SKEW_TOLERANCE_S = 5


def codex_quota(
    session_id: str, root: Path, now: float | None = None
) -> tuple[float, int]:
    """Kontoweit juengsten, noch hinreichend aktuellen 5h-
    Kontingentverbrauch und dessen Fenster-Ablaufzeit lesen
    (verbrauchsfrei, kein CLI-Aufruf).

    Codex schreibt ``token_count``-Ereignisse mit einer
    ``rate_limits``-Momentaufnahme (Felder ``primary``/``secondary``,
    je ``used_percent``/``window_minutes``/``resets_at``) in die lokale
    Sitzungsablage unter ``~/.codex/sessions/JJJJ/MM/TT/rollout-*-
    <session_id>.jsonl`` -- nachgewiesen sowohl fuer interaktive
    Sitzungen als auch fuer ``codex exec`` (Herkunft ``codex_exec`` im
    ``session_meta``-Ereignis). Das Kontingent ist kontoweit, nicht
    sitzungsgebunden: die eigene Sitzung dieser Rolle kann laenger
    nicht mit der API gesprochen haben, waehrend andere Sitzungen
    desselben Kontos es zwischenzeitlich weiter verbraucht haben; ein
    noch nicht abgelaufenes Fenster beweist keinen aktuellen
    Kontostand. Gemessen wird deshalb das zeitlich juengste
    ``token_count``-Ereignis ueber ALLE lokalen Rollouts, ohne
    Fruehabbruch (``_freshest_account_window``): eine Beziehung
    zwischen Datei-Aenderungszeit und dem im Inhalt stehenden
    Ereignis-Zeitstempel ist technisch nicht garantiert (Kopien,
    Wiederherstellung, verzoegertes Schreiben) und traegt deshalb
    keine Suchbegrenzung, bis eine solche Beziehung nachweisbar gilt
    (ki-dev-ablauf-dqv-Nachreview). Das 5h-Fenster ist das mit
    ``window_minutes == FIVE_HOUR_WINDOW_MINUTES``, nicht positional
    ``primary``. ``session_id`` bleibt eine Gueltigkeitspruefung
    (genau eine bekannte Sitzung), nicht die Messquelle.

    Diese Funktion setzt voraus, dass ``root`` (``CODEX_HOME``) fuer
    seine gesamte Standzeit genau ein Konto abbildet -- eine
    dokumentierte Betriebsvoraussetzung, technisch nicht pruefbar, da
    weder ``session_meta`` noch ``rate_limits`` ein Kontomerkmal
    tragen. ``MAX_MEASUREMENT_AGE_S`` begrenzt das Risiko eines
    Kontowechsels zusaetzlich: nur kuerzlich aktive Rollouts werden
    ueberhaupt als Nachweis akzeptiert (ki-dev-ablauf-hju, dreifach
    ueberarbeitet in dqv).
    """
    find_session_rollout(root, session_id)
    event_epoch, used_percent, resets_at = _freshest_account_window(
        root
    )
    now_s = now if now is not None else time.time()
    _require_current_measurement(event_epoch, resets_at, now_s)
    return used_percent, resets_at


def _require_current_measurement(
    event_epoch: float, resets_at: int, now_s: float
) -> None:
    if resets_at <= now_s:
        raise ValueError(
            "Codex-5h-Messwert ist abgelaufen (resets_at in der "
            "Vergangenheit); kein aktueller Nachweis"
        )
    age_s = now_s - event_epoch
    if age_s < -CLOCK_SKEW_TOLERANCE_S:
        raise ValueError(
            f"Codex-5h-Messwert liegt in der Zukunft "
            f"({-age_s:g}s nach 'now'); kein plausibler Nachweis"
        )
    if age_s > MAX_MEASUREMENT_AGE_S:
        raise ValueError(
            f"Codex-5h-Messwert ist zu alt ({age_s:g}s > "
            f"{MAX_MEASUREMENT_AGE_S}s); kein hinreichend aktueller "
            "Nachweis"
        )


def _freshest_account_window(root: Path) -> tuple[float, float, int]:
    """Zeitlich juengstes ``token_count``-Ereignis ueber alle lokalen
    Rollouts. Bewusst ohne Suchbegrenzung (siehe ``codex_quota``);
    Vergleich ueber geparste Epochenwerte, nicht ueber Zeitstempel-
    Strings (unterschiedliche Nachkommastellen-Laenge sortiert als
    Text falsch, z. B. '...:00Z' nach '...:00.500Z')."""
    best = None
    for path in root.glob("*/*/*/rollout-*.jsonl"):
        found = _latest_five_hour_window(path)
        if found is not None and (best is None or found[0] > best[0]):
            best = found
    if best is None:
        raise ValueError("Codex-Rollout hat keine 5h-Kontingentmessung")
    return best


def _epoch_seconds(timestamp: str) -> float:
    try:
        return datetime.fromisoformat(
            timestamp.replace("Z", "+00:00")
        ).timestamp()
    except ValueError as exc:
        raise ValueError(
            f"ungueltiger Codex-Zeitstempel: {timestamp!r}"
        ) from exc


def _latest_five_hour_window(
    path: Path,
) -> tuple[float, float, int] | None:
    """Groesster geparste Zeitwert innerhalb der Datei, nicht die
    physisch letzte Zeile: eine chronologisch sortierte Zeilenfolge
    ist technisch nicht garantiert (ki-dev-ablauf-dqv-Nachreview)."""
    latest = None
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            found = _token_count_window(line)
            if found is not None and (
                latest is None or found[0] > latest[0]
            ):
                latest = found
    return latest


def _token_count_window(line: str) -> tuple[float, float, int] | None:
    row = json.loads(line)
    if not isinstance(row, dict):
        raise ValueError("Codex-Rolloutzeile ist kein Objekt")
    payload = row.get("payload")
    if (
        row.get("type") != "event_msg"
        or not isinstance(payload, dict)
        or payload.get("type") != "token_count"
    ):
        return None
    rate_limits = payload.get("rate_limits")
    if rate_limits is None:
        return None
    timestamp = row.get("timestamp")
    if type(timestamp) is not str or not timestamp:
        raise ValueError("Codex-Rolloutzeile ohne Zeitstempel")
    used_percent, resets_at = _five_hour_window(rate_limits)
    return _epoch_seconds(timestamp), used_percent, resets_at


def _five_hour_window(rate_limits: object) -> tuple[float, int]:
    if not isinstance(rate_limits, dict):
        raise ValueError("Codex-rate_limits ist kein Objekt")
    for window in (
        rate_limits.get("primary"),
        rate_limits.get("secondary"),
    ):
        if not isinstance(window, dict):
            continue
        if window.get("window_minutes") != FIVE_HOUR_WINDOW_MINUTES:
            continue
        used_percent = window.get("used_percent")
        resets_at = window.get("resets_at")
        if (
            type(used_percent) not in (int, float)
            or not math.isfinite(used_percent)
            or used_percent < 0
            or type(resets_at) is not int
        ):
            raise ValueError("Codex-5h-Fenster ungueltig")
        return float(used_percent), resets_at
    raise ValueError("Codex-rate_limits enthaelt kein 5h-Fenster")


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
