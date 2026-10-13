"""Typer-Anbindung von step: ``ki-dev -f ABLAUF step`` (ein Turn
eines Ablaufs) und ``ki-dev step`` (local, Sitzungsimport);
Argumente, Aufrufform, Exitcodes."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from ki_dev.adapter.manual import TransportReadError, send
from ki_dev.flow.model import Flow, FlowError
from ki_dev.ops.checks import PREFLIGHT
from ki_dev.ops.checks.options import PreflightOptionError
from ki_dev.ops.checks.preflight import PreflightConfigError
from ki_dev.ops.context.bead_input import BeadInputInvalidError
from ki_dev.ops.context.beads_reader import (
    BeadsReadError,
    InvalidBeadIdError,
    check_bead_id,
)
from ki_dev.ops.context.limit import HandoffBaseTooLongError
from ki_dev.ops.context.limit_config import (
    LimitConfigInvalidError,
    LimitConfigReadError,
)
from ki_dev.step.boundary import CONSOLE, guideline_choice
from ki_dev.step.exits import fail
from ki_dev.step.feedback import FeedbackConfigError
from ki_dev.step.forms import LOCAL_WORD, MAP_WORD, local_form, map_form
from ki_dev.step.help import HELP, TOOL_HELP
from ki_dev.step.options import PreflightValues, preflight_request
from ki_dev.step.package import AnswerError, StepOps, load_step_ops
from ki_dev.step.projection import (
    Guidelines,
    InputMissingError,
    Output,
    Request,
    handoff_operation,
    step_output,
)
from ki_dev.step.turn import bind_flow

ANSWER_MAX_CHARS = 20000
"""Obergrenze einer Antwortdatei (Zeichen); nie gekürzt."""

STDIN_WORD = "-"


def step_app(flow: Flow, path: Path) -> typer.Typer:
    """Der Befehl ``step`` für den Ablauf aus ``path`` (``ki-dev -f``):
    jedes Paket hat ihn, das Paket liefert nur seine Ops."""
    app = typer.Typer(add_completion=False)

    @app.command(help=HELP)
    def step(
        bead_id: Annotated[
            str, typer.Argument(metavar="BEAD_ID", help="Beads-ID.")
        ],
        position: Annotated[
            str,
            typer.Argument(
                metavar="ZUSTAND",
                help="Zustand mit Übergabe (turn/ask).",
            ),
        ],
        answers: Annotated[
            list[str] | None,
            typer.Argument(
                metavar="[ZUSTAND=DATEI]...",
                help="Antwort eines Zustands (DATEI - liest stdin).",
                show_default=False,
            ),
        ] = None,
        preflight_args: Annotated[
            list[str] | None,
            typer.Option(
                "--preflight-args",
                metavar="NAME=ARGS",
                help="ARGS an die Vorlauf-Prüfung NAME anhängen "
                "(wiederholbar; Teillauf).",
                show_default=False,
            ),
        ] = None,
        preflight_skip: Annotated[
            list[str] | None,
            typer.Option(
                "--preflight-skip",
                metavar="NAME=GRUND",
                help="Vorlauf-Prüfung NAME begründet auslassen "
                "(wiederholbar; Teillauf).",
                show_default=False,
            ),
        ] = None,
    ) -> None:
        run_step(
            flow,
            path,
            bead_id,
            position,
            answers or [],
            PreflightValues(preflight_args or [], preflight_skip or []),
        )

    return app


def run_step(
    flow: Flow,
    path: Path,
    bead_id: str,
    position: str,
    answers: list[str],
    options: PreflightValues,
) -> None:
    """Aufruf prüfen (Exit 2 vor jedem Lesen), Antworten lesen, den
    Turn fahren und die Übergabe ausgeben."""
    ops = _bound(flow, path)
    _check_position(flow, bead_id, position)
    sources = _answer_sources(flow, answers)
    preflight = preflight_request(options, _binds_preflight(flow))
    output = _output(
        Request(bead_id, position, (), preflight),
        sources,
        flow,
        ops,
        guideline_choice(flow, ops),
    )
    send(CONSOLE, "", output.text)
    if output.exit_code:
        raise typer.Exit(code=output.exit_code)


def _output(
    request: Request,
    sources: list[tuple[str, str]],
    flow: Flow,
    ops: StepOps,
    guidelines: Guidelines,
) -> Output:
    """Antworten lesen und den Turn fahren; Fehler werden Exitcodes."""
    try:
        raws = tuple((s, _read(s, src)) for s, src in sources)
        return step_output(
            replace(request, answers=raws), flow, ops, guidelines
        )
    except (
        InvalidBeadIdError,
        AnswerError,
        InputMissingError,
        FeedbackConfigError,
        LimitConfigInvalidError,
        HandoffBaseTooLongError,
    ) as exc:
        fail(str(exc), code=2)
    except BeadInputInvalidError as exc:
        _fail_incomplete(request.bead_id, request.position, exc)
    except BeadsReadError as exc:
        fail(f"Beads-Lesefehler: {exc}", code=1)
    except PreflightOptionError as exc:
        fail(f"Aufruf ungültig: {exc}", code=2)
    except PreflightConfigError as exc:
        fail(f"Vorlauf-Konfiguration ungültig: {exc}", code=2)
    except (TransportReadError, LimitConfigReadError) as exc:
        fail(str(exc), code=1)


def _bound(flow: Flow, path: Path) -> StepOps:
    """Ablauf an Felder und Bausteine binden, Ops des Pakets laden."""
    try:
        bind_flow(flow)
        return load_step_ops(flow)
    except FlowError as exc:
        fail(f"Ablauffehler: {path}: {exc}", code=2)


def _binds_preflight(flow: Flow) -> bool:
    return any(b.do == PREFLIGHT for b in flow.bindings.values())


def _handoff_states(flow: Flow) -> list[str]:
    return [s for s in flow.states if handoff_operation(flow, s)]


def _check_position(flow: Flow, bead_id: str, position: str) -> None:
    """Gültige Beads-ID; nur Zustände mit Übergabe an einen
    Executor."""
    try:
        check_bead_id(bead_id)
    except InvalidBeadIdError as exc:
        fail(str(exc), code=2)
    if (
        position in flow.states
        and handoff_operation(flow, position) is not None
    ):
        return
    reason = (
        "hat keine Übergabe (turn/ask)"
        if position in flow.states
        else "ist kein Zustand"
    )
    fail(
        f"{position} {reason} in {flow.name}; Zustände mit Übergabe: "
        + ", ".join(_handoff_states(flow)),
        code=2,
    )


def _answer_sources(
    flow: Flow, answers: list[str]
) -> list[tuple[str, str]]:
    """``ZUSTAND=DATEI`` je Antwort: ein Zustand mit Übergabe oder
    gebundener Operation, jeder höchstens einmal, stdin höchstens
    einmal."""
    found: list[tuple[str, str]] = []
    for item in answers:
        state, separator, source = item.partition("=")
        if not separator or not state or not source:
            fail(f"Antwort {item!r}: erwartet ZUSTAND=DATEI", code=2)
        if state not in flow.states:
            fail(
                f"Antwort {state}: kein Zustand in {flow.name}", code=2
            )
        if not _answers(flow, state):
            fail(f"Antwort {state}: der Zustand antwortet nie", code=2)
        if any(state == seen for seen, _ in found):
            fail(f"Antwort {state}: doppelt", code=2)
        found.append((state, source))
    if sum(source == STDIN_WORD for _, source in found) > 1:
        fail("stdin (-) höchstens für eine Antwort", code=2)
    return found


def _answers(flow: Flow, state: str) -> bool:
    """Ob ``state`` je eine Antwort hat: Übergabe oder gebundene
    Operation (ihr Ergebnis)."""
    return handoff_operation(flow, state) is not None or any(
        op.do in flow.bindings for op in flow.state(state).operations
    )


def _read(state: str, source: str) -> str:
    what = f"Antwort {state}"
    text = CONSOLE.receive(source, ANSWER_MAX_CHARS, what)
    if len(text) > ANSWER_MAX_CHARS:
        raise AnswerError(
            f"{what} überschreitet {ANSWER_MAX_CHARS} Zeichen; keine "
            "Kürzung"
        )
    return text


def _fail_incomplete(
    bead_id: str, state: str, error: BeadInputInvalidError
) -> NoReturn:
    fields = "\n".join(f"  {path}" for path in error.problems)
    fail(
        f"Bead {bead_id} ist für {state} formal unvollständig:\n"
        f"{fields}",
        code=2,
    )


def step_forms(
    form: Annotated[
        str | None,
        typer.Argument(
            metavar="local|map",
            help="local (freie Sitzung ohne Bead) oder map "
            "(Sitzungsimport).",
        ),
    ] = None,
    agent: Annotated[
        str | None,
        typer.Option(
            "--agent",
            metavar="AGENT",
            help="Anbieter der Quellsitzung (codex oder claude).",
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
    title: Annotated[
        str | None,
        typer.Option(
            "--title",
            metavar="TITEL",
            help="Titel des Snapshots (nur mit map --agent/--session).",
            show_default=False,
        ),
    ] = None,
) -> None:
    if form == LOCAL_WORD:
        local_form(agent, session, title)
    elif form == MAP_WORD or agent is not None or session is not None:
        map_form(form, agent, session, title)
    else:
        fail(
            "Aufruf: ki-dev step local oder ki-dev step map --agent "
            "AGENT --session SESSION_ID --title TITEL; einen Bead "
            "führt ki-dev -f ABLAUF step BEAD_ID ZUSTAND",
            code=2,
        )

step_forms.__doc__ = TOOL_HELP
