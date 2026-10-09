"""Befunde des Vorlaufs für die Reparaturnachricht.

Reiner Text aus dem Bericht der Operation ``checks``: jeder Befehl mit
Status, Ort der Konfiguration und der einmalige Ausweg über
``--preflight-args``. Ohne Ein-/Ausgabe.
"""

from __future__ import annotations

import shlex

from ki_dev.ops.checks.preflight import (
    CONFIG_FILE,
    CONFIG_TABLE,
    PreflightConfig,
    PreflightExecutionError,
    PreflightReport,
    artifact_line,
    format_command_result,
    report_name,
)


def execution_error_finding(exc: PreflightExecutionError) -> str:
    """Artefaktfehler außerhalb eines einzelnen Befehls.

    Bereits gelaufene Befehle (``exc.partial_results``) dürfen dabei
    nicht verlorengehen: Sowohl bestandene als auch fehlgeschlagene
    Korrekturen können den Arbeitsbaum schon verändert haben, ohne
    dass der Bericht das noch zeigen könnte.
    """
    message = f"Vorlauf-Ausführungsfehler: {exc}"
    if exc.partial_results:
        lines = [
            format_command_result(item) for item in exc.partial_results
        ]
        message += (
            "\nBereits gelaufene Befehle vor dem Fehler (PASS- wie "
            "FAIL-Befehle können den Arbeitsbaum bereits verändert "
            "haben; kein automatischer Rückbau):\n" + "\n".join(lines)
        )
    return message


def repair_finding(
    report: PreflightReport, config: PreflightConfig
) -> str:
    """Listet jeden Befehl (auch erfolgreiche und ausgelassene) auf.

    Sowohl bestandene als auch fehlgeschlagene Befehle können den
    Arbeitsbaum bereits verändert haben (z. B. ein Formatter, der eine
    Datei ändert und danach an einer anderen scheitert); kein
    automatischer Rückbau. Ausgelassene Prüfungen und die tatsächlichen
    argv müssen deshalb ebenfalls sichtbar bleiben, nicht nur die
    fehlgeschlagenen Befehle. Abschließend nennt der Befund den Ort der
    Konfiguration und, bei einer fehlgeschlagenen Prüfung, den
    einmaligen Ausweg über --preflight-args.
    """
    lines = [format_command_result(item) for item in report.commands]
    lines.append(artifact_line(report))
    lines.append(f"Konfiguration: {CONFIG_FILE} [{CONFIG_TABLE}]")
    failed_check = _first_failed_check(report, config)
    if failed_check is not None:
        hint = shlex.quote(f"{report_name(failed_check)}=ARGS")
        lines.append(
            f"Einmalig ergänzen: --preflight-args {hint} (ARGS werden "
            "an argv der Prüfung angehängt; Teillauf ohne PASS)"
        )
    return (
        "Vorlauf ohne Review-Übergabe; bereits ausgeführte Befehle "
        "(PASS wie FAIL) wurden nicht automatisch zurückgesetzt:\n"
        + "\n".join(lines)
    )


def _first_failed_check(
    report: PreflightReport, config: PreflightConfig
) -> str | None:
    check_names = {spec.name for spec in config.checks}
    for item in report.commands:
        if item.name in check_names and item.status == "fail":
            return item.name
    return None
