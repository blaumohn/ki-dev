"""Pflichtfelder und strikte Validierung des SafetyProfile/1.

Vertrag: docs/architecture/v1-safety-contract.de.md, Abschnitt D.
Betriebswerte sind REQUIRED_NO_DEFAULT: dieses Modul kennt keine
Vorgabewerte. Ein Modus (quota_mode/evidence_mode) autorisiert allein
nichts; Ausnahmemodi brauchen eine Freigabereferenz (die Referenz
selbst darf auch bei Standardmodi stehen, sie ist dann Grundlage einer
Ueberschreibung im Praezedenzblatt). Nicht abgebildet: benannte
Betreuung und Konto-/Fensterbeleg von SUPERVISED_MANUAL, sowie eine
Zusatzregel terminate_grace_s + kill_wait_s <= call_timeout_s (die
Stop-Wartezeit kommt laut ADR zum Call-Timeout hinzu). Praezedenz, Hash
und Manifest-Snapshot gehoeren zu einem spaeteren Blatt.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from decimal import Decimal, InvalidOperation
from typing import Any

from ki_dev.safety_profile.contract import (
    EvidenceMode,
    QuotaMode,
    ReasonCode,
    SafetyProfile,
)

SCHEMA_VERSION = 1

_SECONDS = (
    "startup_sample_timeout_s",
    "max_measurement_age_s",
    "watchdog_interval_s",
    "terminate_grace_s",
    "kill_wait_s",
    "call_timeout_s",
    "diagnostic_timeout_s",
)
_POSITIVE_INTS = (
    "diagnostic_attempts",
    "split_threshold_tokens",
    "task_cap_tokens",
    "call_cap_tokens",
)
_TEXTS = ("policy_version", "strategy_id", "strategy_revision")
# Reihenfolge (kleiner, groesser) laut Abschnitt D.
_ORDER = (
    ("watchdog_interval_s", "max_measurement_age_s"),
    ("watchdog_interval_s", "startup_sample_timeout_s"),
    ("startup_sample_timeout_s", "call_timeout_s"),
    ("call_cap_tokens", "task_cap_tokens"),
)
FIELD_NAMES = tuple(f.name for f in fields(SafetyProfile))


class ProfileInvalid(ValueError):
    """Profil verletzt den Vertrag; blockiert vor jeder Reservierung."""

    reasons = (ReasonCode.PROFILE_INVALID,)

    def __init__(self, problems: tuple[str, ...]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _is_int(value: object) -> bool:
    return type(value) is int


def _is_seconds(value: object, *, minimum: Decimal | None) -> bool:
    if type(value) is not Decimal or not value.is_finite():
        return False
    return value > 0 if minimum is None else value >= minimum


def _is_text(value: object) -> bool:
    return type(value) is str and bool(value.strip())


def profile_problems(profile: object) -> tuple[str, ...]:
    """Alle Vertragsverletzungen als knappe Feldmeldungen.

    Enthalten keine Werte, nur Feldnamen und Regeln.
    """
    if type(profile) is not SafetyProfile:
        return ("kein SafetyProfile",)
    p: Any = profile
    out: list[str] = []
    if not _is_int(p.schema_version) or p.schema_version != (
        SCHEMA_VERSION
    ):
        out.append(f"schema_version muss {SCHEMA_VERSION} sein")
    out += [
        f"{n} muss nichtleerer Text sein"
        for n in _TEXTS
        if not _is_text(getattr(p, n))
    ]
    out += [
        f"{n} muss endlich und > 0 sein (Decimal)"
        for n in _SECONDS
        if not _is_seconds(getattr(p, n), minimum=None)
    ]
    out += [
        f"{n} muss positive Ganzzahl sein"
        for n in _POSITIVE_INTS
        if not _is_int(getattr(p, n)) or getattr(p, n) < 1
    ]
    if not _is_seconds(p.reserve_factor, minimum=Decimal(1)):
        out.append("reserve_factor muss endlich und >= 1 sein")
    for low, high in _ORDER:
        a, b = getattr(p, low), getattr(p, high)
        if _comparable(a, b) and a > b:
            out.append(f"{low} darf {high} nicht ueberschreiten")
    out += _mode_problems(p)
    return tuple(out)


def _comparable(a: object, b: object) -> bool:
    if type(a) is Decimal and type(b) is Decimal:
        return a.is_finite() and b.is_finite()
    return _is_int(a) and _is_int(b)


def _mode_problems(p: Any) -> list[str]:
    out: list[str] = []
    quota_ok = type(p.quota_mode) is QuotaMode
    evidence_ok = type(p.evidence_mode) is EvidenceMode
    if not quota_ok:
        out.append("quota_mode unbekannt")
    if not evidence_ok:
        out.append("evidence_mode unbekannt")
    ref, ttl = p.authorization_ref, p.quota_evidence_ttl_s
    if ref is not None and not _is_text(ref):
        out.append("authorization_ref muss nichtleerer Text sein")
    supervised = (
        quota_ok and p.quota_mode is QuotaMode.SUPERVISED_MANUAL
    )
    real_work = (
        evidence_ok
        and p.evidence_mode is EvidenceMode.AUTHORIZED_REAL_WORK
    )
    if (supervised or real_work) and not _is_text(ref):
        out.append("Ausnahmemodus ohne authorization_ref")
    if supervised:
        if not _is_seconds(ttl, minimum=None):
            out.append(
                "SUPERVISED_MANUAL braucht endliches "
                "quota_evidence_ttl_s > 0"
            )
    elif quota_ok and ttl is not None:
        out.append("quota_evidence_ttl_s nur bei SUPERVISED_MANUAL")
    return out


def validate_profile(profile: SafetyProfile) -> tuple[ReasonCode, ...]:
    """Leer, wenn gueltig; sonst ``(PROFILE_INVALID,)``."""
    if profile_problems(profile):
        return (ReasonCode.PROFILE_INVALID,)
    return ()


def _decimal(name: str, value: object, problems: list[str]) -> Any:
    if type(value) is Decimal:
        return value
    if _is_int(value):
        return Decimal(value)
    if type(value) in (float, str):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            pass
    problems.append(f"{name} ist keine Zahl")
    return value


def _mode(
    name: str, enum: type, value: object, problems: list[str]
) -> Any:
    if type(value) is enum:
        return value
    if type(value) is str:
        try:
            return enum(value)
        except ValueError:
            pass
    problems.append(f"{name} unbekannt")
    return value


def parse_profile(data: Mapping[str, object]) -> SafetyProfile:
    """Baut ein SafetyProfile aus einer Zuordnung, strikt.

    Fehlende oder zusaetzliche Schluessel, bool als Zahl, NaN/Infinity
    und unbekannte Modi ergeben ``ProfileInvalid``. Es gibt keine
    Vorgaben: ``quota_evidence_ttl_s`` und ``authorization_ref`` muessen
    ausdruecklich (auch als ``None``) genannt werden.
    """
    if not isinstance(data, Mapping):
        raise ProfileInvalid(("Profil ist keine Zuordnung",))
    missing = [n for n in FIELD_NAMES if n not in data]
    extra = sorted(str(k) for k in data if k not in FIELD_NAMES)
    if missing or extra:
        raise ProfileInvalid(
            tuple(f"Feld fehlt: {n}" for n in missing)
            + tuple(f"Feld unbekannt: {n}" for n in extra)
        )
    problems: list[str] = []
    values = dict(data)
    for name in (*_SECONDS, "reserve_factor"):
        values[name] = _decimal(name, values[name], problems)
    ttl = values["quota_evidence_ttl_s"]
    if ttl is not None:
        values["quota_evidence_ttl_s"] = _decimal(
            "quota_evidence_ttl_s", ttl, problems
        )
    values["quota_mode"] = _mode(
        "quota_mode", QuotaMode, values["quota_mode"], problems
    )
    values["evidence_mode"] = _mode(
        "evidence_mode", EvidenceMode, values["evidence_mode"], problems
    )
    profile = SafetyProfile(**values)
    problems += profile_problems(profile)
    if problems:
        raise ProfileInvalid(tuple(dict.fromkeys(problems)))
    return profile
