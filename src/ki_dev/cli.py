"""Kommandozeile fuer ki-dev."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ki_dev.ausfuehrer.run_cli import (
    CONFIG_OPTION,
    RunConfigError,
    result_document,
    resume_run,
    start_from_config,
    status_run,
)
from ki_dev.ausfuehrer.run_runtime import RunResult, RunResumeError
from ki_dev.config_cli import config
from ki_dev.planning_cli import app as planning_app
from ki_dev.run_store import RunStoreError
from ki_dev.session_cli import app as session_app
from ki_dev.step.cli import handoff

console = Console()

app = typer.Typer(
    help=(
        "ki-dev - deklarative Abläufe, ein Ausführer, austauschbare "
        "Agentenadapter."
    ),
    no_args_is_help=True,
    add_completion=False,
)
run_app = typer.Typer(
    help=(
        "Den Bauablauf automatisch bis zum nächsten Halt fahren "
        "(start, resume, status)."
    ),
)
app.add_typer(run_app, name="run")
app.add_typer(planning_app, name="planning")
app.add_typer(session_app, name="session")
app.command("step")(handoff)
app.command("config")(config)


def main() -> None:
    app()


@run_app.callback(invoke_without_command=True)
def run(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option(
            CONFIG_OPTION,
            help="JSON-Konfiguration fuer einen neuen Lauf.",
        ),
    ] = None,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    runs_dir: Annotated[Path, typer.Option("--runs-dir")] = Path(
        ".ki-dev/runs"
    ),
) -> None:
    """Einen neuen ki-dev-Lauf starten."""
    if ctx.invoked_subcommand is None:
        if config is None:
            _abort("--config ist fuer einen neuen Lauf erforderlich")
        _execute(
            lambda: start_from_config(
                config, run_id=run_id, runs_dir=runs_dir
            )
        )


@run_app.command()
def resume(
    run_id: Annotated[str, typer.Argument()],
    answer: Annotated[str | None, typer.Option("--answer")] = None,
    reconcile_result: Annotated[
        Path | None, typer.Option("--reconcile-result")
    ] = None,
    runs_dir: Annotated[Path, typer.Option("--runs-dir")] = Path(
        ".ki-dev/runs"
    ),
) -> None:
    """Einen pausierten ki-dev-Lauf fortsetzen."""
    _execute(
        lambda: resume_run(
            run_id,
            runs_dir=runs_dir,
            answer=answer,
            reconcile_result=reconcile_result,
        )
    )


@run_app.command("status")
def status(
    run_id: Annotated[str, typer.Argument()],
    runs_dir: Annotated[Path, typer.Option("--runs-dir")] = Path(
        ".ki-dev/runs"
    ),
) -> None:
    """Den Status eines Laufs anzeigen, ohne ihn fortzusetzen."""
    _execute(lambda: status_run(run_id, runs_dir=runs_dir))


def _execute(action: Callable[[], RunResult]) -> None:
    try:
        result = action()
    except (RunConfigError, RunResumeError, RunStoreError) as exc:
        _abort(str(exc))
    console.print_json(data=result_document(result))


def _abort(message: str) -> None:
    console.print(f"[red]{message}[/red]")
    raise typer.Exit(code=2)
