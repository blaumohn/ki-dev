"""Optionsprüfung von ``ki-dev -f ABLAUF step``: Exit 2 vor jedem
Lesen."""

from __future__ import annotations

from typing import NamedTuple

from ki_dev.ops.checks.options import (
    PreflightOptionError,
    parse_preflight_args,
    parse_preflight_skip,
)
from ki_dev.step.exits import fail


class PreflightValues(NamedTuple):
    """Rohangaben von --preflight-args/--preflight-skip."""

    args: list[str]
    skip: list[str]

    def __bool__(self) -> bool:
        return bool(self.args or self.skip)

class PreflightRequest(NamedTuple):
    """Geprüfte Vorlauf-Optionen: Zusatzargumente und Auslassungen."""

    extra: dict[str, tuple[str, ...]]
    skip: dict[str, str]

NO_PREFLIGHT_OPTIONS = PreflightRequest({}, {})

def preflight_request(
    options: PreflightValues, preflight: bool
) -> PreflightRequest:
    """--preflight-args/--preflight-skip vor jedem Lesen prüfen; sie
    gelten nur für einen Ablauf, der den Vorlauf bindet
    (``preflight``)."""
    if not options:
        return NO_PREFLIGHT_OPTIONS
    if not preflight:
        fail(
            "--preflight-args/--preflight-skip gelten nur für einen "
            "Ablauf mit Vorlauf (checks.preflight)",
            code=2,
        )
    try:
        return PreflightRequest(
            parse_preflight_args(options.args),
            parse_preflight_skip(options.skip),
        )
    except PreflightOptionError as exc:
        fail(f"Aufruf ungültig: {exc}", code=2)
