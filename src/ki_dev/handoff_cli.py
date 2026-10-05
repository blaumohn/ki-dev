"""Typer-Anbindung für ki-dev handoff."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Annotated, BinaryIO, NamedTuple, NoReturn

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
from ki_dev.handoff_next_turn import (
    FeedbackReadError,
    NextTurnInputError,
    load_feedback_max_chars,
    read_feedback,
    render_repair_turn,
    render_review_turn,
)
from ki_dev.handoff_preflight import (
    CONFIG_FILE,
    CONFIG_TABLE,
    CheckArgsError,
    PreflightConfig,
    PreflightConfigError,
    PreflightExecutionError,
    PreflightReport,
    apply_check_args,
    artifact_line,
    format_command_result,
    load_preflight_config,
    parse_check_args,
    render_review_handoff,
    report_name,
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
  ki-dev handoff projekt-42 --step review --check-args 'tests=-k x'
  ki-dev handoff projekt-42 --step review --review-of materialize
  ki-dev handoff projekt-42 --step review --next-turn
  ki-dev handoff projekt-42 --step review --next-turn --feedback-file -
  ki-dev handoff map --agent codex --session SESSION_ID

REVIEW
  Standard: build. Führt vorab konfigurierte Korrekturen und Tests aus.
  Korrekturen können Dateien ändern. Konfiguration: pyproject.toml,
  tool.ki-dev.handoff.preflight.
  --check-args NAME=ARGS hängt ARGS einmalig an die Prüfung NAME an
  (wiederholbar, z. B. um einen unabhängigen Test abzuwählen).
  --review-of map, graph oder materialize: nur lesen, ohne Vorlauf.

NÄCHSTE NACHRICHT (--step review --next-turn)
  Nach einer Korrektur: Vorlauf (Ziel build) fehlgeschlagen -> Nachricht
  an den Bau-Agenten (stdout, Exit 1); bestanden oder map/graph/
  materialize -> erneute Review-Nachricht (Exit 0).
  --feedback-file DATEI|- hängt eine Rückmeldung des Schreibagenten an
  (UTF-8; - liest stdin; höchstens feedback_max_chars Zeichen, Standard
  600, in pyproject.toml, Abschnitt tool.ki-dev.handoff; nie gekürzt).
  Ohne die Option wird nichts gelesen.

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
    check_args: Annotated[
        list[str] | None,
        typer.Option(
            "--check-args",
            metavar="NAME=ARGS",
            help="ARGS an die Vorlauf-Prüfung NAME anhängen "
            "(wiederholbar); nur mit --step review.",
            show_default=False,
        ),
    ] = None,
    next_turn: Annotated[
        bool,
        typer.Option(
            "--next-turn",
            help="Nächste Nachricht nach einer Korrektur (Bau-Agent "
            "bei Vorlauffehler, sonst Reviewer); nur mit --step "
            "review.",
        ),
    ] = False,
    feedback_file: Annotated[
        str | None,
        typer.Option(
            "--feedback-file",
            metavar="DATEI|-",
            help="Rückmeldung des Schreibagenten (UTF-8; - liest "
            "stdin); nur mit --next-turn.",
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
    check_args = check_args or []
    if agent is not None or session is not None or bead_id == MAP_WORD:
        _map_form(
            bead_id,
            step,
            review_of,
            check_args,
            next_turn or feedback_file is not None,
            agent,
            session,
        )
    else:
        _bead_form(
            bead_id,
            step,
            review_of,
            check_args,
            next_turn,
            feedback_file,
        )


def _bead_form(
    bead_id: str | None,
    step: Step | None,
    review_of: ReviewTarget | None,
    check_args: list[str],
    next_turn: bool,
    feedback_file: str | None,
) -> None:
    if bead_id is None or step is None:
        _fail(
            "Aufruf: BEAD_ID --step STEP oder map --agent codex "
            "--session SESSION_ID",
            code=2,
        )
    extra = _review_options(
        step, review_of, check_args, next_turn, feedback_file
    )
    exit_code = 0
    try:
        issue = read_issue(bead_id, Path.cwd())
        if step is Step.REVIEW and next_turn:
            text, exit_code = _next_turn_handoff(
                issue, review_of, extra, feedback_file
            )
        elif step is Step.REVIEW:
            text = _review_handoff(issue, review_of, extra)
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
    except NextTurnInputError as exc:
        _fail(str(exc), code=2)
    except FeedbackReadError as exc:
        _fail(str(exc), code=1)
    typer.echo(text, nl=False)
    if exit_code:
        raise typer.Exit(code=exit_code)


def _review_options(
    step: Step,
    review_of: ReviewTarget | None,
    check_args: list[str],
    next_turn: bool,
    feedback_file: str | None,
) -> dict[str, tuple[str, ...]]:
    """--review-of/--check-args/--next-turn/--feedback-file vor jedem
    Lesen prüfen.

    Gibt die zerlegten Zusatzargumente zurück; --check-args gilt nur
    für den Vorlauf (Prüfgegenstand build).
    """
    if review_of is not None and step is not Step.REVIEW:
        _fail(
            "--review-of ist nur zusammen mit --step review zulässig",
            code=2,
        )
    if next_turn and step is not Step.REVIEW:
        _fail(
            "--next-turn ist nur zusammen mit --step review zulässig",
            code=2,
        )
    if feedback_file is not None and not next_turn:
        _fail(
            "--feedback-file ist nur zusammen mit --next-turn zulässig",
            code=2,
        )
    if not check_args:
        return {}
    if step is not Step.REVIEW or review_of not in (
        None,
        ReviewTarget.BUILD,
    ):
        _fail(
            "--check-args gilt nur für den Vorlauf: --step review "
            "(Prüfgegenstand build)",
            code=2,
        )
    try:
        return parse_check_args(check_args)
    except CheckArgsError as exc:
        _fail(f"Aufruf ungültig: {exc}", code=2)


def _review_handoff(
    issue: HandoffIssue,
    review_of: ReviewTarget | None,
    extra: dict[str, tuple[str, ...]],
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
    outcome = _preflight_outcome(extra)
    if outcome.failure is not None:
        _fail(outcome.failure, code=1)
    return render_review_handoff(issue, outcome.report)


class _PreflightOutcome(NamedTuple):
    """``failure`` ist der Reparaturbefund; ``None`` heißt bestanden
    (dann liegt ``report`` vor)."""

    report: PreflightReport | None
    failure: str | None


def _preflight_outcome(
    extra: dict[str, tuple[str, ...]],
) -> _PreflightOutcome:
    """Vorlauf für den Prüfgegenstand build; der Bead ist bereits
    validiert. Die Konfiguration wird vollständig geprüft, bevor der
    erste Korrekturbefehl läuft (kein Schreibeffekt vor dieser
    Prüfung)."""
    project_root = Path.cwd()
    config = _with_check_args(
        load_preflight_config(project_root), extra
    )
    try:
        report = run_preflight(config, project_root, _progress)
    except PreflightExecutionError as exc:
        return _PreflightOutcome(None, _execution_error_finding(exc))
    if not report.valid:
        finding = _repair_finding(report, config)
        return _PreflightOutcome(report, finding)
    return _PreflightOutcome(report, None)


def _next_turn_handoff(
    issue: HandoffIssue,
    review_of: ReviewTarget | None,
    extra: dict[str, tuple[str, ...]],
    feedback_file: str | None,
) -> tuple[str, int]:
    """Nächste Nachricht nach einer Korrektur und ihr Exitcode.

    Alle Eingaben (Bead, Grenze, Rückmeldung) sind geprüft, bevor der
    Vorlauf startet. Nur der Prüfgegenstand build läuft durch den
    Vorlauf: Fehlschlag -> Bau-Agent (Exit 1, Nachricht auf stdout),
    Erfolg -> Reviewer. map/graph/materialize gehen ohne Vorlauf zur
    erneuten Review-Übergabe. Die Grenze wird für jedes Ziel gelesen
    und geprüft (ungültiges TOML oder ein ungültiger Wert wird
    abgelehnt); eine fehlende Vorlauf-Konfiguration bleibt für
    map/graph/materialize erlaubt.
    """
    target = review_of or ReviewTarget.BUILD
    problems = validate_handoff(issue, Step.REVIEW, target)
    if problems:
        raise HandoffInvalidError(problems)
    limit = load_feedback_max_chars(Path.cwd())
    feedback = None
    if feedback_file is not None:
        feedback = read_feedback(feedback_file, limit, _stdin_binary)
    if target is not ReviewTarget.BUILD:
        return render_review_turn(issue, target, None, feedback), 0
    outcome = _preflight_outcome(extra)
    if outcome.failure is not None:
        return render_repair_turn(
            issue, outcome.failure, limit, feedback
        ), 1
    text = render_review_turn(issue, target, outcome.report, feedback)
    return text, 0


def _stdin_binary() -> BinaryIO:
    return sys.stdin.buffer


def _with_check_args(
    config: PreflightConfig, extra: dict[str, tuple[str, ...]]
) -> PreflightConfig:
    """Zusatzargumente anwenden; ein unbekannter Prüfname ist ein
    Aufruffehler (Exit 2) vor dem ersten Befehl."""
    try:
        return apply_check_args(config, extra)
    except CheckArgsError as exc:
        _fail(f"Aufruf ungültig: {exc}", code=2)


def _progress(line: str) -> None:
    # stderr: stdout trägt nur die Übergabe (``> uebergabe.txt``).
    typer.echo(line, err=True)


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


def _repair_finding(
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
    einmaligen Ausweg über --check-args.
    """
    lines = [format_command_result(item) for item in report.commands]
    lines.append(artifact_line(report))
    lines.append(f"Konfiguration: {CONFIG_FILE} [{CONFIG_TABLE}]")
    failed_check = _first_failed_check(report, config)
    if failed_check is not None:
        hint = shlex.quote(f"{report_name(failed_check)}=ARGS")
        lines.append(
            f"Einmalig ergänzen: --check-args {hint} (ARGS werden an "
            "argv der Prüfung angehängt)"
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


def _map_form(
    bead_id: str | None,
    step: Step | None,
    review_of: ReviewTarget | None,
    check_args: list[str],
    next_turn_option: bool,
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
    if (
        step is not None
        or review_of is not None
        or check_args
        or next_turn_option
    ):
        _fail(
            "--step/--review-of/--check-args/--next-turn/"
            "--feedback-file lassen sich nicht mit map "
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


def _fail(message: str, *, code: int) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)
