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


def _codex_checked_counts(
    info_usage: object,
) -> tuple[TokenCounts | None, str | None]:
    """Strukturpruefung eines Codex-Usage-Objekts, unabhaengig von
    der CLI-Version: ``(None, Grund)`` wenn keine Zaehler lesbar sind,
    ``(Zaehler, Grund)`` wenn sie lesbar, aber nicht voll
    vertrauenswuerdig sind, ``(Zaehler, None)`` wenn voll gueltig."""
    if not isinstance(info_usage, dict):
        return None, (
            "token_count-Nutzdaten fehlen oder sind kein Objekt"
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
        return None, (
            "Tokenzaehler fehlt, ist ungueltig oder Cache > Input"
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
        return (
            TokenCounts(
                fresh_input=input_total - cached,
                cache_read=cached,
                cache_creation=0,
                output=output,
            ),
            f"reasoning_output_tokens widerspruechlich: {exc}",
        )
    total_raw = info_usage.get("total_tokens")
    reported_total = _nonneg_int(total_raw)
    if total_raw is not None and reported_total is None:
        return tokens, (
            "gemeldetes total_tokens ist kein gueltiger nicht "
            "negativer Ganzzahlwert (Typ: "
            f"{_describe_invalid(total_raw)})"
        )
    if reported_total is not None and reported_total != tokens.total:
        # Empirisch beobachtete Anomalie (echte lokale Rollouts):
        # last_token_usage kann bei Compaction/Kontextereignissen alle
        # Einzelwerte als 0 melden, waehrend total_tokens weiterhin
        # eine alte, ungleich Null-Summe traegt. Die Einzelwerte
        # werden trotzdem mitgeliefert (nicht durch 0 ersetzt), aber
        # als nicht voll vertrauenswuerdig gekennzeichnet.
        return tokens, (
            "gemeldetes total_tokens "
            f"({reported_total}) passt nicht zu Einzelwerten "
            f"({tokens.total}); moeglich bei Compaction/"
            "Kontextereignis"
        )
    return tokens, None


def _codex_valid_total(usage: object) -> int | None:
    """Gesamtwert eines total_token_usage oder last_token_usage, nur
    wenn es strukturell voll gueltig ist -- sonst ist es kein Beleg
    (Summe) bzw. nicht vergleichbar (Requestwert). Unabhaengig von der
    CLI-Version; geordneter und zeitstempelloser Pfad nutzen dieselbe
    Pruefung."""
    tokens, problem = _codex_checked_counts(usage)
    if tokens is None or problem is not None:
        return None
    return tokens.total


_COVERAGE_CONTRADICTION = (
    "kumulative Summe bzw. ihr Zuwachs ist kleiner als der eigene "
    "last_token_usage-Wert desselben Ereignisses; widerspruechlicher "
    "Beleg, Request nicht bestaetigt"
)


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
    tokens, problem = _codex_checked_counts(info_usage)
    if tokens is None:
        return _unavailable(
            "codex",
            source,
            scope,
            problem,
            cli_version=cli_version,
            session_id=session_id,
            event_time=event_time,
        )
    if problem is not None:
        return UsageEvent(
            UsageStatus.PARTIAL,
            "codex",
            source,
            scope,
            cli_version=cli_version,
            session_id=session_id,
            event_time=event_time,
            tokens=tokens,
            detail=problem,
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


def _codex_confirmed_request(
    last_usage: object,
    event_time: float | None,
    *,
    cli_version: str | None,
    session_id: str | None,
) -> UsageEvent:
    return normalize_codex_token_count_usage(
        last_usage,
        scope=CounterScope.PER_REQUEST,
        cli_version=cli_version,
        session_id=session_id,
        event_time=event_time,
    )


def _codex_unconfirmed_request(
    pending: dict,
    *,
    cli_version: str | None,
    session_id: str | None,
    detail: str | None = None,
) -> UsageEvent:
    """Ein last_token_usage, fuer das nie ein eigener oder spaeter
    passender kumulativer Beleg auftauchte: Zahlen bleiben erhalten
    (kein Verwerfen), aber MEASURED waere hier mehr Sicherheit als
    tatsaechlich vorhanden -- eine gleich teure, echte zweite
    Anfrage laesst sich ohne kumulativen Beleg nicht ausschliessen."""
    event = _codex_confirmed_request(
        pending["last_usage"],
        pending["event_time"],
        cli_version=cli_version,
        session_id=session_id,
    )
    if event.status is UsageStatus.MEASURED:
        return replace(
            event,
            status=UsageStatus.PARTIAL,
            detail=detail
            or (
                "last_token_usage ohne eigenen oder spaeter "
                "bestaetigenden kumulativen Beleg beobachtet; eine "
                "gleich teure, echte zweite Anfrage ist ohne "
                "kumulativen Beleg nicht auszuschliessen"
            ),
        )
    if detail is not None:
        # Schon aus anderem Grund (z. B. unbekannte Version) nicht
        # MEASURED: die zusaetzliche Diagnose ergaenzt, statt
        # verloren zu gehen.
        return replace(
            event,
            detail="; ".join(
                part for part in (detail, event.detail) if part
            ),
        )
    return event


def read_codex_rollout_usage(
    path: Path, *, cli_version: str | None = None
) -> CodexRolloutScan:
    """Ein Ereignis mit eigenem, vom vorherigen Stand abweichendem
    total_token_usage (Wachstum oder Reset) bestaetigt sein
    last_token_usage direkt und eigenstaendig -- auch nach einem
    Reset, denn die neue, niedrigere Zaehlerbasis ist selbst ein
    gueltiger Beleg fuer das, was seither dazukam. Bleibt der Zaehler
    dagegen unveraendert, ist nichts Neues dazugekommen. Fehlt der
    kumulative Beleg fuer ein Ereignis ganz, bleibt sein
    last_token_usage als "unbestaetigt" (``pending``) vorgemerkt: ein
    spaeteres Ereignis mit direkt bestaetigtem Beleg und identischem
    Inhalt loest es auf (dieselbe Beobachtung, kein zusaetzlicher
    Request), abweichender Inhalt oder das Dateiende schliessen es
    stattdessen als PARTIAL ab. Reiner Zeitstempel- oder
    Inhaltsvergleich allein belegt nie einen neuen Request (empirisch
    an echten Rollouts bestaetigt: identischer last_token_usage-Inhalt
    ging in allen beobachteten Faellen mit unveraendertem
    total_token_usage einher, nie mit Wachstum).

    Ein Rueckgang irgendwo in der zeitlich geordneten Folge bleibt am
    Ende sichtbar, auch wenn der Zaehler danach wieder waechst
    (Messvertrag: "Zaehlerreset/-rueckgang ... haben explizite
    Ergebnisse"). Die zeitlich juengste Beobachtung eines
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
    pending: dict | None = None
    # Inhalt des im aktuellen Zaehlerabschnitt direkt bestaetigten
    # last_token_usage. Nur innerhalb dieses Abschnitts gilt eine
    # Wiederholung desselben Inhalts als "bereits ausgegeben". Jeder
    # Wechsel der gueltigen Summe beginnt einen neuen Abschnitt und
    # verwirft ihn -- auch ein reines Summenereignis ohne
    # last_token_usage und auch ein Reset zurueck auf denselben
    # Zahlenwert (derselbe Wert, aber ein anderer Abschnitt).
    last_confirmed_content: str | None = None
    reset_detected = False
    invalid_total_count = 0
    latest_total_usage: object = None
    latest_total_time: float | None = None
    latest_total_seen = False
    for event_time, info in ordered:
        total_usage = info.get("total_token_usage")
        # Nur eine strukturell voll gueltige Summe ist ein Beleg; eine
        # ungueltige zaehlt fuer die Request-Erkennung wie eine
        # fehlende und wird am Ende an der Gesamtsumme sichtbar.
        raw_total = _codex_valid_total(total_usage)
        if "total_token_usage" in info and raw_total is None:
            invalid_total_count += 1
        last_usage = info.get("last_token_usage")
        last_content = (
            json.dumps(last_usage, sort_keys=True)
            if last_usage is not None
            else None
        )
        if (
            raw_total is not None
            and prev_cumulative is not None
            and raw_total < prev_cumulative
        ):
            reset_detected = True
        directly_confirmed = (
            raw_total is not None and raw_total != prev_cumulative
        )
        if directly_confirmed:
            last_confirmed_content = None
        current_value = (
            _codex_valid_total(last_usage)
            if last_usage is not None
            else None
        )
        # Was die Summe dieses Ereignisses an neuem Verbrauch belegt:
        # bei Wachstum der Zuwachs, sonst (erste Summe oder Reset auf
        # eine neue Zaehlerbasis) die Summe selbst.
        coverage = (
            raw_total - prev_cumulative
            if raw_total is not None
            and prev_cumulative is not None
            and raw_total > prev_cumulative
            else raw_total
        )
        if (
            directly_confirmed
            and current_value is not None
            and coverage < current_value
        ):
            # Widerspruch: die kumulative Summe enthaelt jeden Request,
            # ihr Zuwachs (bzw. nach Reset die neue Basis) kann also
            # nie kleiner als dessen eigener Wert sein. Ein solches
            # Ereignis ist kein Beleg fuer sein last_token_usage -- es
            # bleibt sichtbar, aber als unvollstaendig mit Diagnose. Ein
            # inhaltsgleiches offenes Pending ist dieselbe Beobachtung
            # und geht darin auf; ein abweichendes bleibt eigenstaendig
            # unbestaetigt.
            same_as_pending = (
                pending is not None
                and pending["content"] == last_content
            )
            if pending is not None and not same_as_pending:
                events.append(
                    _codex_unconfirmed_request(
                        pending,
                        cli_version=effective_cli_version,
                        session_id=file_session_id,
                    )
                )
            observation = (
                pending
                if same_as_pending
                else {
                    "last_usage": last_usage,
                    "event_time": event_time,
                }
            )
            events.append(
                _codex_unconfirmed_request(
                    observation,
                    cli_version=effective_cli_version,
                    session_id=file_session_id,
                    detail=_COVERAGE_CONTRADICTION,
                )
            )
            pending = None
        elif directly_confirmed:
            if (
                last_usage is None
                and pending is not None
                and pending.get("anchored")
            ):
                # Reiner Summenwechsel: ein bei gueltiger Summe
                # beobachtetes Pending gehoert zu seinem (jetzt
                # beendeten) Zaehlerabschnitt und wird von diesem
                # Wechsel nicht bestaetigt -- es bleibt unbestaetigt
                # und verschmilzt nicht mit Lesungen des neuen
                # Abschnitts.
                events.append(
                    _codex_unconfirmed_request(
                        pending,
                        cli_version=effective_cli_version,
                        session_id=file_session_id,
                    )
                )
                pending = None
            if last_usage is not None:
                if pending is not None and pending["content"] == (
                    last_content
                ):
                    # Gleicher Inhalt wie das offene Pending: die Hoehe
                    # des Summenzuwachses entscheidet, welche der drei
                    # Deutungen zutrifft. Deckt er genau eine
                    # Beobachtung, ist es derselbe Vorgang (Pending
                    # entfaellt stillschweigend). Deckt er genau zwei,
                    # sind es zwei echte, zufaellig gleich teure
                    # Anfragen (beide bleiben erhalten). Fehlt die
                    # Vergleichsbasis (kein vorheriger Zaehlerstand),
                    # laesst sich "zwei" trotzdem ausschliessen, wenn
                    # schon die absolute Summe kleiner als das
                    # Doppelte ist (der Zuwachs kann die Summe nie
                    # uebersteigen); dass sie mindestens einen Request
                    # deckt, ist oben bereits sichergestellt -- bei
                    # identischem Inhalt bleibt dann nur "derselbe
                    # Vorgang" als einzige Deutung uebrig. Passt weder
                    # absolute Summe noch Zuwachs zu einer der beiden
                    # Deutungen, ist die Zuordnung ungeklaert -- das
                    # Pending bleibt sichtbar, aber nur als
                    # unbestaetigt.
                    growth = (
                        raw_total - prev_cumulative
                        if prev_cumulative is not None
                        else None
                    )
                    confirmed_two = (
                        growth is not None
                        and current_value is not None
                        and growth == 2 * current_value
                    )
                    confirmed_one = current_value is not None and (
                        growth == current_value
                        or (
                            growth is None
                            and current_value
                            <= raw_total
                            < 2 * current_value
                        )
                    )
                    if confirmed_two:
                        events.append(
                            _codex_confirmed_request(
                                pending["last_usage"],
                                pending["event_time"],
                                cli_version=effective_cli_version,
                                session_id=file_session_id,
                            )
                        )
                    elif not confirmed_one:
                        events.append(
                            _codex_unconfirmed_request(
                                pending,
                                cli_version=effective_cli_version,
                                session_id=file_session_id,
                            )
                        )
                else:
                    if pending is not None:
                        events.append(
                            _codex_unconfirmed_request(
                                pending,
                                cli_version=effective_cli_version,
                                session_id=file_session_id,
                            )
                        )
                events.append(
                    _codex_confirmed_request(
                        last_usage,
                        event_time,
                        cli_version=effective_cli_version,
                        session_id=file_session_id,
                    )
                )
                last_confirmed_content = last_content
                pending = None
        elif raw_total is not None:
            # Bestaetigtes Nicht-Wachstum (raw_total ==
            # prev_cumulative): es ist nichts Neues dazugekommen. Ob
            # das last_token_usage dieses Ereignisses schon ausgegeben
            # ist, haengt davon ab, wozu es passt:
            # - zum im aktuellen Zaehlerabschnitt bestaetigten Inhalt:
            #   Wiederholung einer bereits ausgegebenen Lesung. Ein
            #   inhaltsgleiches Pending ist dieselbe Lesung und
            #   entfaellt; ein abweichendes bleibt davon unerklaert und
            #   wird als unbestaetigt ausgegeben.
            # - zum offenen Pending: Wiederholung einer noch nicht
            #   ausgegebenen Lesung. Sie wird zusammengefuehrt, das
            #   Pending bleibt aber offen -- mindestens eine
            #   unbestaetigte Beobachtung muss erhalten bleiben.
            # - zu keinem von beiden: eine neue, unbelegte Beobachtung;
            #   ein abweichendes Pending wird als unbestaetigt
            #   abgeschlossen, die neue wird vorgemerkt.
            if (
                last_usage is not None
                and last_content == last_confirmed_content
            ):
                if (
                    pending is not None
                    and pending["content"] != last_content
                ):
                    events.append(
                        _codex_unconfirmed_request(
                            pending,
                            cli_version=effective_cli_version,
                            session_id=file_session_id,
                        )
                    )
                pending = None
            elif (
                pending is not None
                and last_usage is not None
                and pending["content"] == last_content
            ):
                pass
            else:
                if pending is not None:
                    events.append(
                        _codex_unconfirmed_request(
                            pending,
                            cli_version=effective_cli_version,
                            session_id=file_session_id,
                        )
                    )
                pending = (
                    {
                        "last_usage": last_usage,
                        "event_time": event_time,
                        "content": last_content,
                        "anchored": True,
                    }
                    if last_usage is not None
                    else None
                )
        elif last_usage is not None and (
            pending is None or pending["content"] != last_content
        ):
            if pending is not None:
                events.append(
                    _codex_unconfirmed_request(
                        pending,
                        cli_version=effective_cli_version,
                        session_id=file_session_id,
                    )
                )
            pending = {
                "last_usage": last_usage,
                "event_time": event_time,
                "content": last_content,
            }
        # Sonst (raw_total is None und last_usage inhaltsgleich mit dem
        # noch offenen, unbestaetigten Pending): dieselbe Beobachtung,
        # nichts Neues zu tun.
        if raw_total is not None:
            prev_cumulative = raw_total
        if "total_token_usage" in info:
            latest_total_usage = total_usage
            latest_total_time = event_time
            latest_total_seen = True
    if pending is not None:
        events.append(
            _codex_unconfirmed_request(
                pending,
                cli_version=effective_cli_version,
                session_id=file_session_id,
            )
        )
    # Nicht zeitlich einordenbare Ereignisse: last_token_usage laesst
    # sich nicht gegen eine Reihenfolge pruefen, bleibt aber erhalten
    # statt stillschweigend verworfen zu werden.
    for info in unordered:
        last_usage = info.get("last_token_usage")
        if last_usage is None:
            continue
        # Derselbe Beleg-Vertrag wie im geordneten Pfad: nur eine
        # strukturell voll gueltige Summe zaehlt, und sie muss den
        # eigenen Requestwert decken (die Summe enthaelt jeden Request).
        own_total = _codex_valid_total(info.get("total_token_usage"))
        own_value = _codex_valid_total(last_usage)
        if own_total is None:
            # Kein Zeitstempel UND kein eigener kumulativer Beleg --
            # genauso unbestaetigt wie im zeitlich geordneten Pfad,
            # nicht stillschweigend als sicher gemessen ausgeben.
            events.append(
                _codex_unconfirmed_request(
                    {"last_usage": last_usage, "event_time": None},
                    cli_version=effective_cli_version,
                    session_id=file_session_id,
                )
            )
        elif own_value is not None and own_total < own_value:
            events.append(
                _codex_unconfirmed_request(
                    {"last_usage": last_usage, "event_time": None},
                    cli_version=effective_cli_version,
                    session_id=file_session_id,
                    detail=_COVERAGE_CONTRADICTION,
                )
            )
        else:
            # Eigener, in sich abgeschlossener Beleg (unabhaengig von
            # jeder Reihenfolge pruefbar): direkt bestaetigt.
            events.append(
                _codex_confirmed_request(
                    last_usage,
                    None,
                    cli_version=effective_cli_version,
                    session_id=file_session_id,
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
        notes = []
        if reset_detected:
            notes.append(
                "kumulativer Zaehler ist an mindestens einer "
                "Stelle der zeitlich geordneten Folge in dieser "
                "Datei gesunken (Reset/Compaction), auch wenn er "
                "seither wieder gewachsen ist; nicht unveraendert "
                "vertrauenswuerdig"
            )
        if invalid_total_count > (
            1 if _codex_valid_total(latest_total_usage) is None else 0
        ):
            # Ungueltig war nicht (nur) die juengste Summe selbst --
            # deren Diagnose steht schon im Ereignis --, sondern eine
            # fruehere: sie belegt keinen Request, darf aber nicht
            # unsichtbar werden.
            notes.append(
                "mindestens eine fruehere total_token_usage-"
                "Momentaufnahme in dieser Datei war strukturell "
                "ungueltig und wurde nicht als Beleg verwendet"
            )
        if notes:
            # Alle zutreffenden Ursachen verketten, keine verdraengt
            # die andere oder die eigene Diagnose des Ereignisses.
            event = replace(
                event,
                status=(
                    UsageStatus.PARTIAL
                    if event.status is UsageStatus.MEASURED
                    else event.status
                ),
                detail="; ".join(
                    part for part in (event.detail, *notes) if part
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
