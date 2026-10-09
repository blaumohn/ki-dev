"""Vorlauf einer Übergabe: Konfiguration laden, Optionen anwenden,
laufen lassen, Ergebnis als Bericht oder Befund.

Die Operation ``checks`` des Planungsablaufs. Ein bestandener Vorlauf
liefert den Bericht, ein gescheiterter den Befund für die
Reparaturnachricht; welches Ereignis daraus folgt, sagt das Ergebnis.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import NamedTuple

from ki_dev.ops.checks.findings import (
    execution_error_finding,
    repair_finding,
)
from ki_dev.ops.checks.options import apply_preflight_options
from ki_dev.ops.checks.preflight import (
    PreflightExecutionError,
    PreflightReport,
    load_preflight_config,
    run_preflight,
)


class ChecksOutcome(NamedTuple):
    """``failure`` ist der Reparaturbefund; ``None`` heißt bestanden
    (dann liegt ``report`` vor)."""

    report: PreflightReport | None
    failure: str | None

    @property
    def event(self) -> str:
        """Ereignis des Zustands, der den Vorlauf ausführt."""
        if self.failure is not None:
            return "checks_failed"
        if self.report is not None and self.report.partial:
            return "checks_partial"
        return "checks_passed"


def run_checks(
    project_root: Path,
    extra: Mapping[str, tuple[str, ...]],
    skip: Mapping[str, str],
    progress: Callable[[str], None],
) -> ChecksOutcome:
    """Vorlauf für den Prüfgegenstand implement; der Bead ist bereits
    validiert. Die Konfiguration wird vollständig geprüft, bevor der
    erste Korrekturbefehl läuft (kein Schreibeffekt vor dieser
    Prüfung); ein Aufruffehler (``PreflightOptionError``) und eine
    ungültige Konfiguration (``PreflightConfigError``) gehen
    unverändert weiter."""
    config = apply_preflight_options(
        load_preflight_config(project_root), extra, skip
    )
    try:
        report = run_preflight(config, project_root, progress)
    except PreflightExecutionError as exc:
        return ChecksOutcome(None, execution_error_finding(exc))
    if not report.valid:
        return ChecksOutcome(report, repair_finding(report, config))
    return ChecksOutcome(report, None)
