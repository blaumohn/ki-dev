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

from dataclasses import dataclass
from enum import StrEnum


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
    """Ob ein Tokenwert genau einen Request oder eine kumulierte
    Sitzungssumme beschreibt. Messvertrag: "Kontextbelegung eines
    Requests, kumulierte Eingabetokens ueber viele Requests und
    Kontingentprozent sind unterschiedliche Messgroessen" -- diese
    Klasse deckt nur die ersten beiden ab; Kontingent bleibt
    ``QuotaMeasurement`` in ``executors/contract.py``."""

    PER_REQUEST = "per_request"
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
    scope = CounterScope.PER_REQUEST
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
    return UsageEvent(
        UsageStatus.MEASURED,
        "claude",
        "cli_result",
        scope,
        cli_version=cli_version,
        requested_model=requested_model,
        session_id=session_id,
        observed_at=observed_at,
        tokens=tokens,
    )


# --- Claude: Sitzungstranskript, einzelne Assistant-Nachricht
# (``message.usage`` in ~/.claude/projects/*/*.jsonl; reichhaltiger
# als der CLI-Turnvertrag, mit ephemeren Cache-/Denk-Unterkategorien).


def normalize_claude_session_message_usage(
    usage: object,
    *,
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
    return UsageEvent(
        UsageStatus.MEASURED,
        "claude",
        "session_message",
        scope,
        confirmed_model=confirmed_model,
        session_id=session_id,
        request_id=request_id,
        event_time=event_time,
        tokens=tokens,
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
    scope = CounterScope.PER_REQUEST
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
    return UsageEvent(
        UsageStatus.MEASURED,
        "codex",
        "cli_turn_completed",
        scope,
        cli_version=cli_version,
        requested_model=requested_model,
        session_id=session_id,
        observed_at=observed_at,
        tokens=tokens,
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
    reasoning = _nonneg_int(info_usage.get("reasoning_output_tokens"))
    reported_total = _nonneg_int(info_usage.get("total_tokens"))
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
    tokens = TokenCounts(
        fresh_input=input_total - cached,
        cache_read=cached,
        cache_creation=0,
        output=output,
        reasoning_output=reasoning,
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
    return UsageEvent(
        UsageStatus.MEASURED,
        "codex",
        source,
        scope,
        cli_version=cli_version,
        session_id=session_id,
        event_time=event_time,
        tokens=tokens,
    )
