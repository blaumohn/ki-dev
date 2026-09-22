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
Zwei Formen; sie lassen sich nicht mischen.

\b
1. ki-dev handoff BEAD_ID --step STEP   (lesend, außer --step review)
2. ki-dev handoff map --agent codex --session SESSION_ID   (schreibt)

Form 1 prüft einen Bead und gibt eine kopierbare Arbeitsübergabe aus.
BEAD_ID ist die Beads-ID (z. B. projekt-42). --step ist erforderlich,
es gibt keine automatische Auswahl.

\b
Schritte und Pflichtfelder (zusätzlich immer id, title, description):
  map          metadata.handoff.source_refs
  graph        metadata.handoff.source_refs
  materialize  metadata.handoff.source_refs
  build        acceptance_criteria, design
  review       acceptance_criteria, design

\b
source_refs ist eine nichtleere Liste nichtleerer Strings, z. B.
  {"handoff":{"source_refs":["docs/design/a.md#L12-L40","bd:karte"]}}
Die Referenzen werden nur als Text weitergegeben, nicht aufgelöst.

Der Befehl liest den Bead nur (bd --readonly show BEAD_ID --json) und
startet keinen Agenten. Fortsetzung von Hand: Ausgabe kopieren (oder
per Umleitung speichern) und in einer passenden getrennten
Agentensitzung einfügen.

\b
--step review erweitert das ausdrücklich um einen deterministischen
Vorlauf ohne Modell: konfigurierte Korrekturen (z. B. Autofixes) und
danach Prüfungen (z. B. Tests) laufen auf dem aktuellen Arbeitsbaum,
bevor die Übergabe entsteht. Konfiguration: pyproject.toml, Tabelle
tool.ki-dev.handoff.preflight, Listen corrections (darf leer sein) und
checks (mindestens ein Eintrag), je Eintrag name, argv, timeout_s.
Details bei Bedarf als lokales Prüfartefakt unter
.local/handoff/preflight; kein Beads-Update, kein Commit, kein Agent.

\b
Form 2 erschließt eine lokale Codex-Sitzung als Quelle für den Schritt
map. --agent und --session sind beide erforderlich; --agent bezeichnet
die Quellsitzung (nur codex), nicht den späteren Kartierungsagenten.
Es gibt keinen Dateipfad und keine automatische Wahl der letzten
Sitzung. Der Sitzungsordner kommt aus KI_DEV_CODEX_SESSIONS_DIR, sonst
CODEX_HOME/sessions, sonst ~/.codex/sessions. Der Dialog wird streng
geprüft (Benutzer/final_answer im Wechsel, ordinal eindeutig); jede
Abweichung bricht ohne Ergebnis ab, Diagnosen nennen nur Prüfcode,
Zeile und Feldpfad, nie Gesprächsinhalt. Schreibwirkung: normalisiertes
Transkript unter .local/handoff/AGENT/SESSION_ID/, dazu ein Quellen-Bead
per bd create (bei gleichem Stand wiederverwendet). stdout ist nur der
kurze map-Auftrag. Serielle Nutzung; kein Agentenstart.

\b
Exit 0: Übergabe auf stdout. Exit 2: Aufruf falsch, Bead formal
unvollständig oder (bei --step review) Vorlauf-Konfiguration ungültig
(jeweils auf stderr, vor jeder Schreibwirkung). Exit 1: bd nicht
lesbar, Sitzung/Quelle nicht verwendbar, oder (bei --step review) eine
Korrektur/Prüfung ist fehlgeschlagen (kurzer Reparaturbefund auf
stderr statt Übergabe).
"""


def handoff(
    bead_id: Annotated[
        str | None,
        typer.Argument(metavar="[BEAD_ID]", help="Beads-ID."),
    ] = None,
    step: Annotated[
        Step | None,
        typer.Option(
            "--step",
            help="map | graph | materialize | build | review",
            show_default=False,
        ),
    ] = None,
    agent: Annotated[
        str | None,
        typer.Option(
            "--agent",
            help="Anbieter der Quellsitzung (nur codex).",
            show_default=False,
        ),
    ] = None,
    session: Annotated[
        str | None,
        typer.Option(
            "--session",
            help="Sitzungs-ID der Quellsitzung.",
            show_default=False,
        ),
    ] = None,
) -> None:
    if agent is not None or session is not None or bead_id == MAP_WORD:
        _map_form(bead_id, step, agent, session)
    else:
        _bead_form(bead_id, step)


def _bead_form(bead_id: str | None, step: Step | None) -> None:
    if bead_id is None or step is None:
        _fail(
            "Aufruf: BEAD_ID --step STEP oder map --agent codex "
            "--session SESSION_ID",
            code=2,
        )
    try:
        issue = read_issue(bead_id, Path.cwd())
        if step is Step.REVIEW:
            text = _review_handoff(issue)
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


def _review_handoff(issue: HandoffIssue) -> str:
    """Deterministischer Vorlauf vor der Review-Übergabe (Step.REVIEW).

    Validiert Bead und Konfiguration vollständig, bevor der erste
    Korrekturbefehl läuft (kein Schreibeffekt vor dieser Prüfung).
    Bei einem Prüf-/Ausführungsfehler bricht dies mit Exit 1 und einem
    kurzen Reparaturbefund ab, statt eine Übergabe zu liefern.
    """
    problems = validate_handoff(issue, Step.REVIEW)
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
    """Git-/Artefaktfehler außerhalb eines einzelnen Befehls.

    Bereits gelaufene Befehle (``exc.partial_results``) dürfen dabei
    nicht verlorengehen: Erfolgreiche Korrekturen können den
    Arbeitsbaum schon verändert haben, ohne dass der Bericht das noch
    zeigen könnte.
    """
    message = f"Vorlauf-Ausführungsfehler: {exc}"
    if exc.partial_results:
        lines = [
            format_command_result(item) for item in exc.partial_results
        ]
        message += (
            "\nBereits gelaufene Befehle vor dem Fehler (erfolgreiche "
            "PASS-Befehle wurden nicht automatisch zurückgesetzt):\n"
            + "\n".join(lines)
        )
    return message


def _repair_finding(report: PreflightReport) -> str:
    """Listet jeden Befehl (auch erfolgreiche und ausgelassene) auf.

    Erfolgreiche Korrekturen können den Arbeitsbaum bereits verändert
    haben (kein automatischer Rückbau); ausgelassene Prüfungen und die
    tatsächlichen argv müssen deshalb sichtbar bleiben, nicht nur die
    fehlgeschlagenen Befehle.
    """
    lines = [format_command_result(item) for item in report.commands]
    if all(item.status == "pass" for item in report.commands):
        lines.append(
            "- Quellstand hat sich während der Prüfungen verändert; "
            "Bericht ungültig"
        )
    return (
        "Vorlauf ohne Review-Übergabe (Details unter "
        f"{ARTIFACT_DIR}); erfolgreiche PASS-Befehle wurden nicht "
        "automatisch zurückgesetzt:\n" + "\n".join(lines)
    )


def _map_form(
    bead_id: str | None,
    step: Step | None,
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
    if step is not None:
        _fail(
            "--step lässt sich nicht mit map --agent/--session mischen",
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
