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
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from ki_dev.executors.claude_cli import (
    VERIFIED_CLI_VERSION as _CLAUDE_VERIFIED_VERSION,
)
from ki_dev.executors.codex_cli import (
    VERIFIED_CLI_VERSION as _CODEX_VERIFIED_VERSION,
)


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


def _describe_invalid(value: object) -> str:
    """Nur der Typname, nie der Wert selbst.

    Ausgabe-/Inhaltsgrenze (wu0.2-Akzeptanzkriterium 4): ein
    Fremdwert (auch ein Sentinel-Gespraechstext oder ein beliebig
    langer String) wird ausschliesslich durch Typ und den ohnehin
    festen Fehlergrund im umgebenden Text beschrieben -- nie durch
    einen Ausschnitt seines Inhalts, auch nicht gekuerzt.
    """
    return type(value).__name__


# Lokal tatsaechlich verifizierte CLI-Versionen (siehe
# executors/claude_cli.py/codex_cli.py, dieselbe Konstante --
# ki-dev-ablauf-u3c prueft die Durchsetzung dieses Bezugs im
# Executor selbst). Ein plausibel geformter, aber nicht verifizierter
# Versionswert (z. B. "999.999.999") ist damit kein implizit
# gueltiger Messwert (Messvertrag).
_KNOWN_SUPPORTED_VERSIONS: dict[str, frozenset[str]] = {
    "claude": frozenset({_CLAUDE_VERIFIED_VERSION}),
    "codex": frozenset({_CODEX_VERIFIED_VERSION}),
}


def _measured_or_partial(
    provider: str, version: object, version_field: str
) -> tuple[UsageStatus, str]:
    """Messvertrag: "unbekannte Version ist kein implizit gueltiger
    Messwert". Ohne (oder mit nicht lokal verifizierter) Version
    bleiben die Zahlen erhalten (kein Verwerfen), der Status sinkt
    aber von MEASURED auf PARTIAL."""
    if not isinstance(version, str) or not version:
        return (
            UsageStatus.PARTIAL,
            f"{version_field} unbekannt "
            f"({_describe_invalid(version)}); Messwert nicht als "
            "vollstaendig verifiziert eingestuft",
        )
    supported = _KNOWN_SUPPORTED_VERSIONS.get(provider, frozenset())
    if version not in supported:
        return (
            UsageStatus.PARTIAL,
            f"{version_field} ist keine lokal verifizierte Version; "
            "Messwert nicht als vollstaendig verifiziert eingestuft",
        )
    return UsageStatus.MEASURED, ""


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
    status, note = _measured_or_partial(
        "claude", cli_version, "cli_version"
    )
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
        "claude", schema_version, "schema_version"
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
    status, note = _measured_or_partial(
        "codex", cli_version, "cli_version"
    )
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
                "negativer Ganzzahlwert (Typ: "
                f"{_describe_invalid(total_raw)})"
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
    status, note = _measured_or_partial(
        "codex", cli_version, "cli_version"
    )
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
    # Auf Byte-Ebene trennen: 0x0A (Zeilenumbruch) kommt in gueltigem
    # UTF-8 nie innerhalb einer Mehrbyte-Sequenz vor, das Trennen ist
    # also sicher, bevor ueberhaupt dekodiert wird. Ein aktiver
    # Schreibvorgang kann sonst mitten in einem Mehrbyte-Zeichen enden;
    # ein vollstaendiger Datei-Decode wuerde dann mit UnicodeDecodeError
    # abbrechen und auch bereits vollstaendige Zeilen verlieren.
    raw = path.read_bytes()
    incomplete_last_line = bool(raw) and not raw.endswith(b"\n")
    byte_lines = raw.split(b"\n")
    # Bei vollstaendigem Inhalt erzeugt der abschliessende
    # Zeilenumbruch eine leere letzte Zeile; bei unvollstaendigem
    # Inhalt ist die letzte Zeile noch nicht fertig geschrieben. Beide
    # werden gleich verworfen, nicht als Nutzzeile geparst.
    if incomplete_last_line or (byte_lines and byte_lines[-1] == b""):
        byte_lines = byte_lines[:-1]
    rows: list[dict] = []
    corrupt: list[int] = []
    for number, raw_line in enumerate(byte_lines, start=1):
        if not raw_line.strip():
            continue
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            corrupt.append(number)
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


def _codex_session_meta(rows: tuple[dict, ...]) -> tuple[
    str | None, str | None
]:
    """``session_meta``.payload traegt ``id`` (Sitzungskennung, deckt
    sich mit dem UUID-Teil des Rollout-Dateinamens) und
    ``cli_version`` -- empirisch an echten lokalen Rollouts bestaetigt,
    nicht nur vom Aufrufer erratbar."""
    for row in rows:
        if row.get("type") != "session_meta":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        session_id = payload.get("id")
        cli_version = payload.get("cli_version")
        return (
            session_id if isinstance(session_id, str) and session_id
            else None,
            cli_version if isinstance(cli_version, str) and cli_version
            else None,
        )
    return None, None


def _codex_token_count_snapshots(
    rows: tuple[dict, ...],
) -> tuple[list[tuple[float, dict]], list[dict]]:
    """``token_count``-Ereignisse mit gueltigem ``info``-Objekt,
    getrennt in zeitlich einordenbare (fuer Reihenfolge-abhaengige
    Pruefungen) und nicht einordenbare (fehlender/ungueltiger
    Zeitstempel)."""
    ordered: list[tuple[float, dict]] = []
    unordered: list[dict] = []
    for row in rows:
        if row.get("type") != "event_msg":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != (
            "token_count"
        ):
            continue
        info = payload.get("info")
        if not isinstance(info, dict):
            continue
        event_time = _iso_to_epoch(row.get("timestamp"))
        if event_time is None:
            unordered.append(info)
        else:
            ordered.append((event_time, info))
    ordered.sort(key=lambda item: item[0])
    return ordered, unordered


def read_codex_rollout_usage(
    path: Path, *, cli_version: str | None = None
) -> CodexRolloutScan:
    """last_token_usage zaehlt als neuer Request, wenn entweder das
    gepaarte total_token_usage seit dem vorherigen Ereignis gewachsen
    ist, oder -- ohne einen solchen kumulativen Beleg -- sein Inhalt
    vom unmittelbar vorangegangenen last_token_usage abweicht.
    Zeitstempel allein belegt nie einen neuen Request; ein fehlender
    kumulativer Beleg belegt nie eine sichere Dopplung (empirisch an
    echten Rollouts bestaetigt: identischer last_token_usage-Inhalt
    ging in allen beobachteten Faellen mit unveraendertem
    total_token_usage einher, nie mit Wachstum). Die
    Vergleichsbasis fuer Wachstum ist immer der zeitlich zuletzt
    beobachtete Wert, nicht das historische Maximum -- nach einem
    Reset muessen Requests oberhalb des neuen, niedrigeren Standes
    wieder erkannt werden. Ein Rueckgang irgendwo in der zeitlich
    geordneten Folge bleibt sichtbar, auch wenn der Zaehler danach
    wieder waechst (Messvertrag: "Zaehlerreset/-rueckgang ... haben
    explizite Ergebnisse"). Die zeitlich juengste Beobachtung eines
    ``total_token_usage``-Schluessels zaehlt als "letzte Summe",
    unabhaengig davon, ob ihr Inhalt gueltig ist -- eine spaetere
    ungueltige Beobachtung darf nicht stillschweigend durch eine
    aeltere gueltige ersetzt werden.
    """
    read = read_jsonl_lenient(path)
    file_session_id, file_cli_version = _codex_session_meta(read.rows)
    effective_cli_version = file_cli_version or cli_version
    ordered, unordered = _codex_token_count_snapshots(read.rows)

    events: list[UsageEvent] = []
    prev_cumulative: int | None = None
    prev_last_content: str | None = None
    reset_detected = False
    latest_total_usage: object = None
    latest_total_time: float | None = None
    latest_total_seen = False
    for event_time, info in ordered:
        total_usage = info.get("total_token_usage")
        raw_total = (
            _nonneg_int(total_usage.get("total_tokens"))
            if isinstance(total_usage, dict)
            else None
        )
        last_usage = info.get("last_token_usage")
        last_content = (
            json.dumps(last_usage, sort_keys=True)
            if last_usage is not None
            else None
        )
        if raw_total is not None:
            is_new_request = (
                prev_cumulative is None or raw_total > prev_cumulative
            )
        else:
            # Ohne kumulativen Beleg ist Inhaltsgleichheit mit der
            # unmittelbar vorangegangenen Zeile das einzig verfuegbare
            # Duplikatsignal; abweichender Inhalt zaehlt als neu,
            # Gleichheit taeuscht ohne Beleg keine Dopplung vor,
            # sondern nur eine bereits gesehene Beobachtung.
            is_new_request = last_content != prev_last_content
        if raw_total is not None:
            if (
                prev_cumulative is not None
                and raw_total < prev_cumulative
            ):
                reset_detected = True
            # Zuletzt beobachteter Wert, nicht das historische
            # Maximum: nach einem Reset muss die Vergleichsbasis neu
            # beginnen, sonst verschwinden Requests oberhalb des
            # neuen, aber unterhalb des alten Standes spurlos.
            prev_cumulative = raw_total
        if last_content is not None:
            prev_last_content = last_content
        if last_usage is not None and is_new_request:
            events.append(
                normalize_codex_token_count_usage(
                    last_usage,
                    scope=CounterScope.PER_REQUEST,
                    cli_version=effective_cli_version,
                    session_id=file_session_id,
                    event_time=event_time,
                )
            )
        if "total_token_usage" in info:
            latest_total_usage = total_usage
            latest_total_time = event_time
            latest_total_seen = True
    # Nicht zeitlich einordenbare Ereignisse: last_token_usage laesst
    # sich nicht gegen eine Reihenfolge pruefen, bleibt aber erhalten
    # statt stillschweigend verworfen zu werden.
    for info in unordered:
        last_usage = info.get("last_token_usage")
        if last_usage is not None:
            events.append(
                normalize_codex_token_count_usage(
                    last_usage,
                    scope=CounterScope.PER_REQUEST,
                    cli_version=effective_cli_version,
                    session_id=file_session_id,
                    event_time=None,
                )
            )
    if latest_total_seen:
        event = normalize_codex_token_count_usage(
            latest_total_usage,
            scope=CounterScope.CUMULATIVE_SESSION,
            cli_version=effective_cli_version,
            session_id=file_session_id,
            event_time=latest_total_time,
        )
        if reset_detected and event.status is UsageStatus.MEASURED:
            event = replace(
                event,
                status=UsageStatus.PARTIAL,
                detail=(
                    "kumulativer Zaehler ist an mindestens einer "
                    "Stelle der zeitlich geordneten Folge in dieser "
                    "Datei gesunken (Reset/Compaction), auch wenn er "
                    "seither wieder gewachsen ist; nicht unveraendert "
                    "vertrauenswuerdig"
                ),
            )
        events.append(event)
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
