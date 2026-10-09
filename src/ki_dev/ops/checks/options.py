"""Aufrufoptionen des Vorlaufs: --preflight-args und --preflight-skip.

Zerlegt und prüft die Angaben vor jeder Schreibwirkung und wendet sie
auf die geladene Vorlauf-Konfiguration an. Beide Optionen begrenzen
nur den Prüfumfang konfigurierter Prüfungen (checks); Korrekturen sind
weder ergänzbar noch auslassbar. Jede Angabe macht den Lauf zum
Teillauf (``PreflightReport.partial``), der keinen PASS trägt.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import cast

from jsonschema import Draft202012Validator

from ki_dev.flow.model import PASS
from ki_dev.ops.checks.preflight import (
    ARGV_SCHEMA,
    PreflightConfig,
    argv_character_problem,
    report_name,
)
from ki_dev.review_decision import ReviewContractError, ReviewVerdict

ARGS_OPTION = "--preflight-args"
SKIP_OPTION = "--preflight-skip"

# Grund einer Auslassung: kurz, einzeilig, ohne Steuerzeichen; er
# erscheint im Bericht und im Agentenkontext.
SKIP_REASON_SCHEMA = {
    "type": "string",
    "minLength": 1,
    "maxLength": 200,
    "pattern": r"^[^\x00-\x1f\x7f]*\S[^\x00-\x1f\x7f]*$",
}
_ARGV_VALIDATOR = Draft202012Validator(ARGV_SCHEMA)
_REASON_VALIDATOR = Draft202012Validator(SKIP_REASON_SCHEMA)


class PreflightOptionError(ValueError):
    """Vorlauf-Option ungültig; Aufruffehler vor jeder Wirkung."""


def parse_preflight_args(
    values: Sequence[str],
) -> dict[str, tuple[str, ...]]:
    """``NAME=ARGS``-Angaben in Prüfname -> Zusatzargumente übersetzen.

    ARGS werden wie in einer Shell zerlegt (``shlex.split``) und
    unterliegen derselben argv-Regel wie die Konfiguration, aber keiner
    Längengrenze. Rohwerte erscheinen nicht in Fehlermeldungen.
    """
    return {
        name: _extra_args(text, label)
        for name, text, label in _pairs(values, ARGS_OPTION, "ARGS")
    }


def parse_preflight_skip(values: Sequence[str]) -> dict[str, str]:
    """``NAME=GRUND``-Angaben in Prüfname -> Auslassungsgrund."""
    parsed: dict[str, str] = {}
    pairs = _pairs(values, SKIP_OPTION, "GRUND")
    for name, reason, label in pairs:
        if not _REASON_VALIDATOR.is_valid(reason):
            raise PreflightOptionError(
                f"{label}: GRUND muss einzeilig, nichtleer und "
                f"höchstens {SKIP_REASON_SCHEMA['maxLength']} Zeichen "
                "lang sein"
            )
        parsed[name] = reason
    return parsed


def apply_preflight_options(
    config: PreflightConfig,
    extra: Mapping[str, tuple[str, ...]],
    skip: Mapping[str, str],
) -> PreflightConfig:
    """Zusatzargumente anhängen und Auslassungen markieren.

    Ein unbekannter oder Korrektur-Name und eine Prüfung, die zugleich
    ergänzt und ausgelassen werden soll, sind Aufruffehler, kein
    stilles Ignorieren.
    """
    check_names = [spec.name for spec in config.checks]
    for option, names in ((ARGS_OPTION, extra), (SKIP_OPTION, skip)):
        for name in names:
            if name not in check_names:
                raise PreflightOptionError(
                    f"{option}: {report_name(name)!r} ist keine "
                    "konfigurierte Prüfung (vorhanden: "
                    f"{', '.join(report_name(n) for n in check_names)})"
                )
    both = sorted(set(extra) & set(skip))
    if both:
        raise PreflightOptionError(
            f"{report_name(both[0])!r} ist zugleich mit {ARGS_OPTION} "
            f"und {SKIP_OPTION} angegeben"
        )
    checks = tuple(
        replace(
            spec,
            argv=spec.argv + extra.get(spec.name, ()),
            added=extra.get(spec.name, ()),
            skip_reason=skip.get(spec.name),
        )
        for spec in config.checks
    )
    return replace(config, checks=checks)


def _pairs(
    values: Sequence[str], option: str, value_name: str
) -> list[tuple[str, str, str]]:
    """``NAME=WERT`` zerlegen; NAME nichtleer und nur einmal."""
    pairs: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for position, value in enumerate(values, start=1):
        name, separator, text = value.partition("=")
        label = f"{option} (Angabe {position})"
        if not separator or not name.strip():
            raise PreflightOptionError(
                f"{label}: erwartet NAME={value_name}"
            )
        if name in seen:
            raise PreflightOptionError(
                f"{label}: Prüfung mehrfach angegeben; Angaben "
                "zusammenfassen"
            )
        seen.add(name)
        pairs.append((name, text, label))
    return pairs


def _extra_args(text: str, label: str) -> tuple[str, ...]:
    try:
        args = shlex.split(text)
    except ValueError as exc:
        raise PreflightOptionError(
            f"{label}: ARGS nicht zerlegbar (Quoting unvollständig)"
        ) from exc
    if not _ARGV_VALIDATOR.is_valid(args):
        raise PreflightOptionError(f"{label}: ARGS ist leer")
    problem = argv_character_problem(args)
    if problem:
        raise PreflightOptionError(f"{label}: ARGS {problem}")
    return tuple(args)


# --- Steuerfelder der Review-Antwort (5we) ---------------------------

_TEXT_MAP = {
    "type": "object",
    "additionalProperties": {"type": "string"},
}
CONTROL_SCHEMA = {
    "preflight_args": _TEXT_MAP,
    "preflight_skip": _TEXT_MAP,
}
"""Optionale Felder der Review-Antwort; ihre Werte prüft
:func:`check_control` wie die CLI-Optionen."""


def control_from(
    extras: Mapping[str, object],
) -> tuple[dict[str, str], dict[str, str]]:
    """Vorgeschlagene Prüfsteuerung (Zusatzargumente, Auslassungen)."""
    args = cast(Mapping[str, str], extras.get("preflight_args", {}))
    skip = cast(Mapping[str, str], extras.get("preflight_skip", {}))
    return dict(args), dict(skip)


def check_control(
    verdict: ReviewVerdict,
    extras: Mapping[str, object],
    load_config: Callable[[], PreflightConfig],
) -> None:
    """Steuerfelder gegen die Vorlauf-Konfiguration prüfen: nie bei
    PASS, Werte wie die CLI-Optionen. ``load_config`` läuft nur bei
    Steuerfeldern; seine Fehler gibt es unverändert weiter."""
    args, skip = control_from(extras)
    if not (args or skip):
        return
    if verdict.event == PASS:
        raise ReviewContractError(
            "preflight_args/preflight_skip: bei PASS nicht erlaubt"
        )
    try:
        apply_preflight_options(
            load_config(),
            parse_preflight_args(_as_pairs(args)),
            parse_preflight_skip(_as_pairs(skip)),
        )
    except PreflightOptionError as exc:
        raise ReviewContractError(str(exc)) from exc


def _as_pairs(values: Mapping[str, str]) -> list[str]:
    return [f"{name}={text}" for name, text in values.items()]
