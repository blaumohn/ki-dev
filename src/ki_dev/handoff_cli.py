"""Typer-Anbindung für ki-dev handoff."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from ki_dev.beads_reader import (
    BeadsReadError,
    InvalidBeadIdError,
    read_issue,
)
from ki_dev.beads_source import BeadsSourceError
from ki_dev.executors.session_transcript import (
    TranscriptError,
    TranscriptRequestError,
)
from ki_dev.executors.transcript import validate_session_request
from ki_dev.handoff import (
    HandoffInvalidError,
    HandoffIssue,
    ReviewTarget,
    Step,
    render_handoff,
    validate_handoff,
)
from ki_dev.handoff_map import map_handoff
from ki_dev.handoff_preflight import (
    ARTIFACT_DIR,
    PreflightConfigError,
    PreflightExecutionError,
    PreflightReport,
    format_command_result,
    load_preflight_config,
    render_review_handoff,
    run_preflight,
)
from ki_dev.handoff_source import HandoffSourceError

MAP_WORD = "map"

HELP = """\
Eine Arbeitsübergabe für eine neue Agentensitzung ausgeben.

AUFRUFE
  ki-dev handoff BEAD_ID --step STEP
    Übergabe aus einem vorhandenen Bead erstellen.
  ki-dev handoff map --agent codex --session SESSION_ID
    Codex-Sitzung als Quelle importieren und Kartierung vorbereiten.

SCHRITTE (--step)
  map          Anforderungen aus Rohnotizen kartieren.
  graph        Aus der Karte einzelne Vorgänge ableiten.
  materialize  Einen Vorgang ausführungsreif beschreiben.
  build        Den beschriebenen Auftrag umsetzen.
  review       Ein Ergebnis in einer getrennten Sitzung prüfen.

BEISPIELE
  ki-dev handoff projekt-42 --step map
  ki-dev handoff projekt-42 --step graph
  ki-dev handoff projekt-42 --step materialize
  ki-dev handoff projekt-42 --step build > uebergabe.txt
  ki-dev handoff projekt-42 --step review
  ki-dev handoff projekt-42 --step review --review-of materialize
  ki-dev handoff map --agent codex --session SESSION_ID

REVIEW
  Standard: build. Führt vorab konfigurierte Korrekturen und Tests aus.
  Korrekturen können Dateien ändern. Konfiguration: pyproject.toml,
  tool.ki-dev.handoff.preflight.
  --review-of map, graph oder materialize: nur lesen, ohne Vorlauf.

SITZUNGSIMPORT (map --agent codex --session SESSION_ID)
  Schreibt ein Transkript unter .local/handoff/ und legt einen
  Quellen-Bead an (bei gleichem Stand wiederverwendet).
  SESSION_ID durch die ID ersetzen.
  Statt einer Beads-ID; nicht mit --step kombinieren.

Ausgabe kopieren und in einer neuen Agentensitzung einfügen.
Der Befehl startet keinen Agenten.

Details zu Pflichtfeldern, Konfiguration und Fehlern: docs/handoff.de.md
"""


def handoff(
    bead_id: Annotated[
        str | None,
        typer.Argument(
            metavar="[BEAD_ID]",
            help="Beads-ID oder map für den Sitzungsimport.",
        ),
    ] = None,
    step: Annotated[
        Step | None,
        typer.Option(
            "--step",
            metavar="STEP",
            help="Schritt der Übergabe (für BEAD_ID erforderlich).",
            show_default=False,
        ),
    ] = None,
    review_of: Annotated[
        ReviewTarget | None,
        typer.Option(
            "--review-of",
            metavar="ZIEL",
            help="map, graph, materialize oder build (Standard); "
            "nur mit --step review.",
            show_default=False,
        ),
    ] = None,
    agent: Annotated[
        str | None,
        typer.Option(
            "--agent",
            metavar="AGENT",
            help="Anbieter der Quellsitzung (nur codex).",
            show_default=False,
        ),
    ] = None,
    session: Annotated[
        str | None,
        typer.Option(
            "--session",
            metavar="SESSION_ID",
            help="Sitzungs-ID der Quellsitzung.",
            show_default=False,
        ),
    ] = None,
) -> None:
    if agent is not None or session is not None or bead_id == MAP_WORD:
        _map_form(bead_id, step, review_of, agent, session)
    else:
        _bead_form(bead_id, step, review_of)


def _bead_form(
    bead_id: str | None,
    step: Step | None,
    review_of: ReviewTarget | None,
) -> None:
    if bead_id is None or step is None:
        _fail(
            "Aufruf: BEAD_ID --step STEP oder map --agent codex "
            "--session SESSION_ID",
            code=2,
        )
    if review_of is not None and step is not Step.REVIEW:
        _fail(
            "--review-of ist nur zusammen mit --step review zulässig",
            code=2,
        )
    try:
        issue = read_issue(bead_id, Path.cwd())
        if step is Step.REVIEW:
            text = _review_handoff(issue, review_of)
        else:
            text = render_handoff(issue, step)
    except InvalidBeadIdError as exc:
        _fail(str(exc), code=2)
    except HandoffInvalidError as exc:
        fields = "\n".join(f"  {path}" for path in exc.problems)
        _fail(
            f"Bead {bead_id} ist für Schritt {step.value} formal "
            f"unvollständig:\n{fields}",
            code=2,
        )
    except BeadsReadError as exc:
        _fail(f"Beads-Lesefehler: {exc}", code=1)
    except PreflightConfigError as exc:
        _fail(f"Vorlauf-Konfiguration ungültig: {exc}", code=2)
    typer.echo(text, nl=False)


def _review_handoff(
    issue: HandoffIssue, review_of: ReviewTarget | None
) -> str:
    """Übergabe für ``--step review``.

    Nur für den (Standard- oder ausdrücklichen) Prüfgegenstand build
    läuft der deterministische Vorlauf aus handoff_preflight: Bead und
    Konfiguration werden vollständig validiert, bevor der erste
    Korrekturbefehl läuft (kein Schreibeffekt vor dieser Prüfung); ein
    Prüf-/Ausführungsfehler bricht mit Exit 1 und einem kurzen
    Reparaturbefund ab, statt eine Übergabe zu liefern. Für
    map/graph/materialize ist das Review eine reine Quellenprüfung:
    kein Vorlauf, keine pyproject.toml nötig, keine Prozessaufrufe.
    """
    if review_of not in (None, ReviewTarget.BUILD):
        return render_handoff(issue, Step.REVIEW, review_of)
    problems = validate_handoff(issue, Step.REVIEW, review_of)
    if problems:
        raise HandoffInvalidError(problems)
    project_root = Path.cwd()
    config = load_preflight_config(project_root)
    try:
        report = run_preflight(config, project_root)
    except PreflightExecutionError as exc:
        _fail(_execution_error_finding(exc), code=1)
    if not report.valid:
        _fail(_repair_finding(report), code=1)
    return render_review_handoff(issue, report)


def _execution_error_finding(exc: PreflightExecutionError) -> str:
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


def _repair_finding(report: PreflightReport) -> str:
    """Listet jeden Befehl (auch erfolgreiche und ausgelassene) auf.

    Sowohl bestandene als auch fehlgeschlagene Befehle können den
    Arbeitsbaum bereits verändert haben (z. B. ein Formatter, der eine
    Datei ändert und danach an einer anderen scheitert); kein
    automatischer Rückbau. Ausgelassene Prüfungen und die tatsächlichen
    argv müssen deshalb ebenfalls sichtbar bleiben, nicht nur die
    fehlgeschlagenen Befehle.
    """
    lines = [format_command_result(item) for item in report.commands]
    return (
        "Vorlauf ohne Review-Übergabe (Details unter "
        f"{ARTIFACT_DIR}); bereits ausgeführte Befehle (PASS wie "
        "FAIL) wurden nicht automatisch zurückgesetzt:\n"
        + "\n".join(lines)
    )


def _map_form(
    bead_id: str | None,
    step: Step | None,
    review_of: ReviewTarget | None,
    agent: str | None,
    session: str | None,
) -> None:
    if bead_id != MAP_WORD:
        _fail(
            "Sitzungsform: ki-dev handoff map --agent codex --session "
            "SESSION_ID (nicht mit BEAD_ID oder anderen "
            "Positionsargumenten mischen)",
            code=2,
        )
    if step is not None or review_of is not None:
        _fail(
            "--step/--review-of lassen sich nicht mit map "
            "--agent/--session mischen",
            code=2,
        )
    if agent is None or session is None:
        _fail("--agent und --session sind beide erforderlich", code=2)
    try:
        validate_session_request(agent, session)
    except TranscriptRequestError as exc:
        _fail(str(exc), code=2)
    try:
        text = map_handoff(agent, session, Path.cwd())
    except TranscriptError as exc:
        details = "\n".join(f"  {problem}" for problem in exc.problems)
        _fail(f"Sitzung nicht verwendbar:\n{details}", code=1)
    except (
        BeadsSourceError,
        BeadsReadError,
        HandoffSourceError,
    ) as exc:
        _fail(f"Quellenübergabe fehlgeschlagen: {exc}", code=1)
    except HandoffInvalidError as exc:
        _fail(
            "Quellen-Bead formal unvollständig: "
            + ", ".join(exc.problems),
            code=1,
        )
    typer.echo(text, nl=False)


handoff.__doc__ = HELP


def _fail(message: str, *, code: int) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)
