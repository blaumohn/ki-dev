"""Provider-uebergreifender Tokenmessvertrag (ki-dev-ablauf-wu0.2).

Normalisiert Rohverbrauchsdaten aus Claude- und Codex-Quellen (CLI-
Turnergebnis und lokale Sitzungs-/Rollout-Dateien) auf eine gemeinsame,
versionierte Form. Reine deterministische Normalisierung: kein
Modellaufruf, keine Freigabeentscheidung, keine Zurechnung zu Auftrag/
Lauf (das bleibt ``loop_safety``/``CallLedger``, ki-dev-ablauf-wu0.3).

Providersemantik ist nicht identisch: Codex liefert ``input_tokens``
inklusive Cache (bestaetigt an echten lokalen Rollouts, siehe
_normalize_codex_component_usage), Claude liefert ``input_tokens``,
``cache_read_input_tokens`` und ``cache_creation_input_tokens`` als drei
getrennte Felder. Reasoning/Thinking ist bei beiden Anbietern bereits in
``output_tokens`` enthalten, kein zusaetzlicher Summand (empirisch an
echten lokalen Sitzungen/Rollouts geprueft: Codex
``reasoning_output_tokens <= output_tokens`` und
``total_tokens == input_tokens + output_tokens``; Claude
``output_tokens_details.thinking_tokens <= output_tokens`` und
``cache_creation.ephemeral_5m_input_tokens +
_1h_input_tokens == cache_creation_input_tokens``).
Diese Pruefung erfolgte ausschliesslich ueber Feldnamen/Zaehler
lokaler Dateien, nie ueber deren Rohinhalt (siehe AGENTS.md,
Abschnitt Verbrauchsmessung).

Architekturquelle: docs/architecture/tokenmessung-estimatoren.de.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class UsageStatus(StrEnum):
    """Vollstaendigkeit einer Tokenmessung, disjunkt von den Werten
    selbst (analog ``ContextStatus``/``QuotaStatus`` in
    ``executors/contract.py``, aber vierwertig: eine Quelle kann intern
    widerspruechlich und damit nur teilweise vertrauenswuerdig sein).

    ``MEASURED``: alle Kategorien vorhanden und mit einer vom Anbieter
    gemeldeten Gesamtsumme konsistent (soweit eine solche existiert).
    ``PARTIAL``: Kategorien vorhanden, aber intern widerspruechlich
    (z. B. gemeldete Gesamtsumme passt nicht zu den Einzelwerten) oder
    unvollstaendig -- die Zahlen werden mitgeliefert, aber als nicht
    voll vertrauenswuerdig gekennzeichnet, nicht stillschweigend als
    ``0`` verworfen.
    ``UNAVAILABLE``: keine nutzbaren Tokenwerte in dieser Quelle.
    ``UNSUPPORTED``: dieser Quellentyp liefert grundsaetzlich keine
    Tokenmessung (analog ``ContextStatus.UNSUPPORTED``).
    """

    MEASURED = "measured"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


class CounterScope(StrEnum):
    """Ob ein Tokenwert genau einen Modell-Request, eine ganze CLI-
    Turnantwort (moeglicherweise mehrere interne Requests, z. B. durch
    Werkzeugnutzung) oder eine kumulierte Sitzungssumme beschreibt.
    Messvertrag: "Kontextbelegung eines Requests, kumulierte
    Eingabetokens ueber viele Requests und Kontingentprozent sind
    unterschiedliche Messgroessen"; "CLI-Gesamtsummen und darin
    enthaltene Einzelrequests dienen dem Abgleich, nicht einer
    doppelten Buchung". Kontingent bleibt ``QuotaMeasurement`` in
    ``executors/contract.py``."""

    PER_REQUEST = "per_request"
    CALL_TOTAL = "call_total"
    CUMULATIVE_SESSION = "cumulative_session"


@dataclass(frozen=True)
class TokenCounts:
    """Normalisierte Tokenkategorien; jede Tokenmenge genau einmal
    enthalten. ``fresh_input`` ist Input ohne Cache-Anteil (bei Codex
    bereits um den Cache-Anteil bereinigt, siehe Moduldoc).
    ``reasoning_output`` und die ephemeren Cache-Unterkategorien sind
    informative, bereits in ``output`` bzw. ``cache_creation``
    enthaltene Unterkategorien -- nicht zusaetzlich zu ``total``
    addieren."""

    fresh_input: int
    cache_read: int
    cache_creation: int
    output: int
    reasoning_output: int | None = None
    cache_creation_ephemeral_5m: int | None = None
    cache_creation_ephemeral_1h: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "fresh_input",
            "cache_read",
            "cache_creation",
            "output",
        ):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(
                    f"TokenCounts.{name} muss eine nicht negative "
                    "Ganzzahl sein"
                )
        if self.reasoning_output is not None:
            if (
                type(self.reasoning_output) is not int
                or self.reasoning_output < 0
            ):
                raise ValueError(
                    "TokenCounts.reasoning_output muss eine nicht "
                    "negative Ganzzahl sein"
                )
            if self.reasoning_output > self.output:
                raise ValueError(
                    "TokenCounts.reasoning_output darf output nicht "
                    "ueberschreiten (Unterkategorie, kein Summand)"
                )
        ephemeral = (
            self.cache_creation_ephemeral_5m,
            self.cache_creation_ephemeral_1h,
        )
        if any(v is not None for v in ephemeral):
            if any(v is None for v in ephemeral):
                raise ValueError(
                    "ephemere Cache-Unterkategorien nur gemeinsam "
                    "angeben"
                )
            if any(type(v) is not int or v < 0 for v in ephemeral):
                raise ValueError(
                    "ephemere Cache-Unterkategorien muessen nicht "
                    "negative Ganzzahlen sein"
                )
            if ephemeral[0] + ephemeral[1] != self.cache_creation:
                raise ValueError(
                    "ephemere Cache-Unterkategorien summieren nicht "
                    "auf cache_creation"
                )

    @property
    def total(self) -> int:
        return (
            self.fresh_input
            + self.cache_read
            + self.cache_creation
            + self.output
        )


@dataclass(frozen=True)
class UsageEvent:
    """Ein normalisierter Verbrauchsmesswert mit Herkunft.

    Enthaelt bewusst keine Bead-/Lauf-/Rollenzurechnung: die
    Verbindung zu Auftrag, Aufruf und Sitzung ist Aufgabe der
    Verbrauchsbilanz (ki-dev-ablauf-wu0.3), nicht dieses Messvertrags.
    """

    status: UsageStatus
    provider: str
    source: str
    counter_scope: CounterScope
    schema_version: str | None = None
    cli_version: str | None = None
    requested_model: str | None = None
    confirmed_model: str | None = None
    session_id: str | None = None
    request_id: str | None = None
    event_time: float | None = None
    observed_at: float | None = None
    tokens: TokenCounts | None = None
    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.status, UsageStatus):
            raise TypeError(
                "UsageEvent.status muss ein UsageStatus sein"
            )
        if not self.provider:
            raise ValueError("UsageEvent.provider darf nicht leer sein")
        if not self.source:
            raise ValueError("UsageEvent.source darf nicht leer sein")
        if not isinstance(self.counter_scope, CounterScope):
            raise TypeError(
                "UsageEvent.counter_scope muss ein CounterScope sein"
            )
        if self.status in (UsageStatus.MEASURED, UsageStatus.PARTIAL):
            if self.tokens is None:
                raise ValueError(
                    "UsageEvent.tokens ist bei MEASURED/PARTIAL "
                    "erforderlich"
                )
        elif self.tokens is not None:
            raise ValueError(
                "UsageEvent.tokens ist nur bei MEASURED/PARTIAL erlaubt"
            )


def _unavailable(
    provider: str,
    source: str,
    scope: CounterScope,
    detail: str,
    **kwargs,
) -> UsageEvent:
    return UsageEvent(
        UsageStatus.UNAVAILABLE,
        provider,
        source,
        scope,
        detail=detail,
        **kwargs,
    )


def _nonneg_int(value: object) -> int | None:
    if type(value) is not int or value < 0:
        return None
    return value


def _measured_or_partial(
    version: str | None, version_field: str
) -> tuple[UsageStatus, str]:
    """Messvertrag: "unbekannte Version ist kein implizit gueltiger
    Messwert". Ohne Version bleiben die Zahlen erhalten (kein
    Verwerfen), der Status sinkt aber von MEASURED auf PARTIAL."""
    if version:
        return UsageStatus.MEASURED, ""
    return (
        UsageStatus.PARTIAL,
        f"{version_field} unbekannt; Messwert nicht als vollstaendig "
        "verifiziert eingestuft",
    )


# --- Claude: CLI-Turnergebnis (``claude -p --output-format json``,
# das "result"-Ereignis; flache Felder, siehe
# executors/metering.py:_claude_usage). ---


def normalize_claude_cli_result(
    usage: object,
    *,
    cli_version: str | None = None,
    requested_model: str | None = None,
    session_id: str | None = None,
    observed_at: float | None = None,
) -> UsageEvent:
    # Ein CLI-Aufruf kann intern mehrere Modell-Requests umfassen
    # (z. B. Werkzeugnutzung); das "result"-Ereignis ist deren
    # Gesamtsumme, kein Einzel-Request (siehe CounterScope-Docstring).
    scope = CounterScope.CALL_TOTAL
    if not isinstance(usage, dict):
        return _unavailable(
            "claude",
            "cli_result",
            scope,
            "usage fehlt oder ist kein Objekt",
            cli_version=cli_version,
            requested_model=requested_model,
            session_id=session_id,
            observed_at=observed_at,
        )
    fields = {
        key: _nonneg_int(usage.get(key))
        for key in (
            "input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "output_tokens",
        )
    }
    if any(value is None for value in fields.values()):
        return _unavailable(
            "claude",
            "cli_result",
            scope,
            "Tokenzaehler fehlt oder ist ungueltig",
            cli_version=cli_version,
            requested_model=requested_model,
            session_id=session_id,
            observed_at=observed_at,
        )
    tokens = TokenCounts(
        fresh_input=fields["input_tokens"],
        cache_read=fields["cache_read_input_tokens"],
        cache_creation=fields["cache_creation_input_tokens"],
        output=fields["output_tokens"],
    )
    status, note = _measured_or_partial(cli_version, "cli_version")
    return UsageEvent(
        status,
        "claude",
        "cli_result",
        scope,
        cli_version=cli_version,
        requested_model=requested_model,
        session_id=session_id,
        observed_at=observed_at,
        tokens=tokens,
        detail=note,
    )


# --- Claude: Sitzungstranskript, einzelne Assistant-Nachricht
# (``message.usage`` in ~/.claude/projects/*/*.jsonl; reichhaltiger
# als der CLI-Turnvertrag, mit ephemeren Cache-/Denk-Unterkategorien).


def normalize_claude_session_message_usage(
    usage: object,
    *,
    schema_version: str | None = None,
    confirmed_model: str | None = None,
    session_id: str | None = None,
    request_id: str | None = None,
    event_time: float | None = None,
) -> UsageEvent:
    scope = CounterScope.PER_REQUEST
    if not isinstance(usage, dict):
        return _unavailable(
            "claude",
            "session_message",
            scope,
            "usage fehlt oder ist kein Objekt",
            schema_version=schema_version,
            confirmed_model=confirmed_model,
            session_id=session_id,
            request_id=request_id,
            event_time=event_time,
        )
    fields = {
        key: _nonneg_int(usage.get(key))
        for key in (
            "input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "output_tokens",
        )
    }
    if any(value is None for value in fields.values()):
        return _unavailable(
            "claude",
            "session_message",
            scope,
            "Tokenzaehler fehlt oder ist ungueltig",
            schema_version=schema_version,
            confirmed_model=confirmed_model,
            session_id=session_id,
            request_id=request_id,
            event_time=event_time,
        )
    reasoning = None
    details = usage.get("output_tokens_details")
    if isinstance(details, dict):
        reasoning = _nonneg_int(details.get("thinking_tokens"))
    ephemeral_5m = ephemeral_1h = None
    creation = usage.get("cache_creation")
    if isinstance(creation, dict):
        ephemeral_5m = _nonneg_int(
            creation.get("ephemeral_5m_input_tokens")
        )
        ephemeral_1h = _nonneg_int(
            creation.get("ephemeral_1h_input_tokens")
        )
        if ephemeral_5m is None or ephemeral_1h is None:
            ephemeral_5m = ephemeral_1h = None
    try:
        tokens = TokenCounts(
            fresh_input=fields["input_tokens"],
            cache_read=fields["cache_read_input_tokens"],
            cache_creation=fields["cache_creation_input_tokens"],
            output=fields["output_tokens"],
            reasoning_output=reasoning,
            cache_creation_ephemeral_5m=ephemeral_5m,
            cache_creation_ephemeral_1h=ephemeral_1h,
        )
    except ValueError as exc:
        return UsageEvent(
            UsageStatus.PARTIAL,
            "claude",
            "session_message",
            scope,
            schema_version=schema_version,
            confirmed_model=confirmed_model,
            session_id=session_id,
            request_id=request_id,
            event_time=event_time,
            tokens=TokenCounts(
                fresh_input=fields["input_tokens"],
                cache_read=fields["cache_read_input_tokens"],
                cache_creation=fields["cache_creation_input_tokens"],
                output=fields["output_tokens"],
            ),
            detail=f"Unterkategorien widerspruechlich: {exc}",
        )
    status, note = _measured_or_partial(
        schema_version, "schema_version"
    )
    return UsageEvent(
        status,
        "claude",
        "session_message",
        scope,
        schema_version=schema_version,
        confirmed_model=confirmed_model,
        session_id=session_id,
        request_id=request_id,
        event_time=event_time,
        tokens=tokens,
        detail=note,
    )


# --- Codex: CLI-Turnergebnis (``codex exec --json``,
# ``turn.completed``-Ereignis, siehe
# executors/metering.py:codex_result). ---


def normalize_codex_turn_usage(
    usage: object,
    *,
    cli_version: str | None = None,
    requested_model: str | None = None,
    session_id: str | None = None,
    observed_at: float | None = None,
) -> UsageEvent:
    # Ein CLI-Turn kann intern mehrere Modell-Requests umfassen (z. B.
    # Werkzeugnutzung); ``turn.completed`` ist deren Gesamtsumme, kein
    # Einzel-Request (siehe CounterScope-Docstring).
    scope = CounterScope.CALL_TOTAL
    if not isinstance(usage, dict):
        return _unavailable(
            "codex",
            "cli_turn_completed",
            scope,
            "usage fehlt oder ist kein Objekt",
            cli_version=cli_version,
            requested_model=requested_model,
            session_id=session_id,
            observed_at=observed_at,
        )
    input_total = _nonneg_int(usage.get("input_tokens"))
    cached = _nonneg_int(usage.get("cached_input_tokens"))
    output = _nonneg_int(usage.get("output_tokens"))
    if (
        input_total is None
        or cached is None
        or output is None
        or cached > input_total
    ):
        return _unavailable(
            "codex",
            "cli_turn_completed",
            scope,
            "Tokenzaehler fehlt, ist ungueltig oder Cache > Input",
            cli_version=cli_version,
            requested_model=requested_model,
            session_id=session_id,
            observed_at=observed_at,
        )
    tokens = TokenCounts(
        fresh_input=input_total - cached,
        cache_read=cached,
        cache_creation=0,
        output=output,
    )
    status, note = _measured_or_partial(cli_version, "cli_version")
    return UsageEvent(
        status,
        "codex",
        "cli_turn_completed",
        scope,
        cli_version=cli_version,
        requested_model=requested_model,
        session_id=session_id,
        observed_at=observed_at,
        tokens=tokens,
        detail=note,
    )


# --- Codex: lokale Rollout-Datei, ``token_count``-Ereignis
# (``payload.info.last_token_usage``/``total_token_usage``, siehe
# executors/metering.py:codex_quota und Moduldoc oben). ---


def normalize_codex_token_count_usage(
    info_usage: object,
    *,
    scope: CounterScope,
    cli_version: str | None = None,
    session_id: str | None = None,
    event_time: float | None = None,
) -> UsageEvent:
    source = (
        "rollout_last_token_usage"
        if scope is CounterScope.PER_REQUEST
        else "rollout_total_token_usage"
    )
    if not isinstance(info_usage, dict):
        return _unavailable(
            "codex",
            source,
            scope,
            "token_count-Nutzdaten fehlen oder sind kein Objekt",
            cli_version=cli_version,
            session_id=session_id,
            event_time=event_time,
        )
    input_total = _nonneg_int(info_usage.get("input_tokens"))
    cached = _nonneg_int(info_usage.get("cached_input_tokens"))
    output = _nonneg_int(info_usage.get("output_tokens"))
    if (
        input_total is None
        or cached is None
        or output is None
        or cached > input_total
    ):
        return _unavailable(
            "codex",
            source,
            scope,
            "Tokenzaehler fehlt, ist ungueltig oder Cache > Input",
            cli_version=cli_version,
            session_id=session_id,
            event_time=event_time,
        )
    reasoning = _nonneg_int(info_usage.get("reasoning_output_tokens"))
    try:
        tokens = TokenCounts(
            fresh_input=input_total - cached,
            cache_read=cached,
            cache_creation=0,
            output=output,
            reasoning_output=reasoning,
        )
    except ValueError as exc:
        # reasoning_output_tokens > output_tokens: die Unterkategorie
        # ist unglaubwuerdig, die Hauptkategorien bleiben es nicht.
        tokens = TokenCounts(
            fresh_input=input_total - cached,
            cache_read=cached,
            cache_creation=0,
            output=output,
        )
        return UsageEvent(
            UsageStatus.PARTIAL,
            "codex",
            source,
            scope,
            cli_version=cli_version,
            session_id=session_id,
            event_time=event_time,
            tokens=tokens,
            detail=f"reasoning_output_tokens widerspruechlich: {exc}",
        )
    total_raw = info_usage.get("total_tokens")
    reported_total = _nonneg_int(total_raw)
    total_present_but_invalid = (
        total_raw is not None and reported_total is None
    )
    if total_present_but_invalid:
        return UsageEvent(
            UsageStatus.PARTIAL,
            "codex",
            source,
            scope,
            cli_version=cli_version,
            session_id=session_id,
            event_time=event_time,
            tokens=tokens,
            detail=(
                "gemeldetes total_tokens ist kein gueltiger nicht "
                f"negativer Ganzzahlwert: {total_raw!r}"
            ),
        )
    if reported_total is not None and reported_total != tokens.total:
        # Empirisch beobachtete Anomalie (echte lokale Rollouts):
        # last_token_usage kann bei Compaction/Kontextereignissen alle
        # Einzelwerte als 0 melden, waehrend total_tokens weiterhin
        # eine alte, ungleich Null-Summe traegt. Die Einzelwerte
        # werden trotzdem mitgeliefert (nicht durch 0 ersetzt), aber
        # als nicht voll vertrauenswuerdig gekennzeichnet.
        return UsageEvent(
            UsageStatus.PARTIAL,
            "codex",
            source,
            scope,
            cli_version=cli_version,
            session_id=session_id,
            event_time=event_time,
            tokens=tokens,
            detail=(
                "gemeldetes total_tokens "
                f"({reported_total}) passt nicht zu Einzelwerten "
                f"({tokens.total}); moeglich bei Compaction/"
                "Kontextereignis"
            ),
        )
    status, note = _measured_or_partial(cli_version, "cli_version")
    return UsageEvent(
        status,
        "codex",
        source,
        scope,
        cli_version=cli_version,
        session_id=session_id,
        event_time=event_time,
        tokens=tokens,
        detail=note,
    )


# --- Sparsame JSONL-Extraktion (wu0.2-Akzeptanzkriterien 2/3):
# vollstaendiger, zustandsloser Einzelscan je Aufruf. Ein
# inkrementeller Index bleibt optionale spaetere Beschleunigung
# (Akzeptanzkriterium 5); ein zustandsloser Vollscan ist von sich aus
# idempotent, da er ausschliesslich vom aktuellen Dateiinhalt abhaengt
# und keinen Lesefortschritt speichert. ---


@dataclass(frozen=True)
class LenientJsonlRead:
    """Ergebnis eines toleranten Volldurchlaufs einer JSONL-Datei.

    ``incomplete_last_line`` heisst: die Datei endet nicht auf einen
    Zeilenumbruch, die letzte Zeile wird also vermutlich noch
    geschrieben und bleibt unverarbeitet -- ein erneuter Aufruf nach
    weiterem Schreiben liest sie vollstaendig nach. ``corrupt_lines``
    sind 1-basierte Zeilennummern abgeschlossener, aber nicht als
    JSON-Objekt lesbarer Zeilen: sichtbar gemacht, nicht stillschweigend
    uebersprungen, ohne den restlichen Scan abzubrechen.
    """

    rows: tuple[dict, ...]
    corrupt_lines: tuple[int, ...]
    incomplete_last_line: bool


def read_jsonl_lenient(path: Path) -> LenientJsonlRead:
    text = path.read_text(encoding="utf-8")
    incomplete_last_line = bool(text) and not text.endswith("\n")
    lines = text.split("\n")
    # Bei vollstaendigem Text erzeugt der abschliessende Zeilenumbruch
    # einen leeren letzten Split; bei unvollstaendigem Text ist die
    # letzte Zeile noch nicht fertig geschrieben. Beide werden gleich
    # verworfen, nicht als Nutzzeile geparst.
    if incomplete_last_line or (lines and lines[-1] == ""):
        lines = lines[:-1]
    rows: list[dict] = []
    corrupt: list[int] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            corrupt.append(number)
            continue
        if not isinstance(row, dict):
            corrupt.append(number)
            continue
        rows.append(row)
    return LenientJsonlRead(
        tuple(rows), tuple(corrupt), incomplete_last_line
    )


def _iso_to_epoch(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        ).timestamp()
    except ValueError:
        return None


@dataclass(frozen=True)
class CodexRolloutScan:
    """Aus einer lokalen Codex-Rollout-Datei extrahierte
    Verbrauchsereignisse: ein ``UsageEvent`` je ``token_count``-
    Ereignis mit ``last_token_usage`` (PER_REQUEST) sowie zusaetzlich
    genau ein ``UsageEvent`` fuer die zeitlich juengste
    ``total_token_usage``-Momentaufnahme (CUMULATIVE_SESSION,
    Ereignisreihenfolge in der Datei ist nicht garantiert, siehe
    executors/metering.py:_latest_five_hour_window)."""

    events: tuple[UsageEvent, ...]
    corrupt_lines: tuple[int, ...]
    incomplete_last_line: bool


def read_codex_rollout_usage(
    path: Path, *, cli_version: str | None = None
) -> CodexRolloutScan:
    read = read_jsonl_lenient(path)
    events: list[UsageEvent] = []
    latest_total: tuple[float, object] | None = None
    for row in read.rows:
        if row.get("type") != "event_msg":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != (
            "token_count"
        ):
            continue
        event_time = _iso_to_epoch(row.get("timestamp"))
        info = payload.get("info")
        info = info if isinstance(info, dict) else {}
        last_usage = info.get("last_token_usage")
        if last_usage is not None:
            events.append(
                normalize_codex_token_count_usage(
                    last_usage,
                    scope=CounterScope.PER_REQUEST,
                    cli_version=cli_version,
                    event_time=event_time,
                )
            )
        total_usage = info.get("total_token_usage")
        if (
            total_usage is not None
            and event_time is not None
            and (latest_total is None or event_time > latest_total[0])
        ):
            latest_total = (event_time, total_usage)
    if latest_total is not None:
        event_time, total_usage = latest_total
        events.append(
            normalize_codex_token_count_usage(
                total_usage,
                scope=CounterScope.CUMULATIVE_SESSION,
                cli_version=cli_version,
                event_time=event_time,
            )
        )
    return CodexRolloutScan(
        tuple(events), read.corrupt_lines, read.incomplete_last_line
    )


@dataclass(frozen=True)
class ClaudeSessionScan:
    """Aus einer lokalen Claude-Sitzungstranskript-Datei extrahierte
    Verbrauchsereignisse: ein ``UsageEvent`` je Assistant-Nachricht,
    dedupliziert per Nachrichten-ID (Streaming kann dieselbe
    Modellantwort auf mehrere Zeilen aufteilen, siehe
    scripts/analyze_claude_usage.py). ``<synthetic>``-Modellantworten
    (keine echte Messung) werden ausgelassen."""

    events: tuple[UsageEvent, ...]
    corrupt_lines: tuple[int, ...]
    incomplete_last_line: bool


def read_claude_session_usage(path: Path) -> ClaudeSessionScan:
    read = read_jsonl_lenient(path)
    by_key: dict[object, dict] = {}
    fallback_index = 0
    for row in read.rows:
        if row.get("type") != "assistant":
            continue
        message = row.get("message")
        if not isinstance(message, dict):
            continue
        if message.get("model") == "<synthetic>":
            continue
        if message.get("usage") is None:
            continue
        message_id = message.get("id")
        if not isinstance(message_id, str) or not message_id:
            fallback_index += 1
            message_id = f"_row_{fallback_index}"
        by_key[message_id] = row
    events = tuple(
        normalize_claude_session_message_usage(
            row["message"].get("usage"),
            schema_version=row.get("version"),
            confirmed_model=row["message"].get("model"),
            session_id=row.get("sessionId"),
            request_id=row.get("requestId"),
            event_time=_iso_to_epoch(row.get("timestamp")),
        )
        for row in by_key.values()
    )
    return ClaudeSessionScan(
        events, read.corrupt_lines, read.incomplete_last_line
    )
