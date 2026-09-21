"""Kommandozeile fuer ki-dev."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from ki_dev.handoff_cli import handoff
from ki_dev.loop_cli import (
    LoopConfigError,
    result_document,
    resume_run,
    start_from_config,
    status_run,
)
from ki_dev.loop_runtime import LoopResumeError, LoopRunResult
from ki_dev.planning_cli import app as planning_app
from ki_dev.run_store import RunStoreError

console = Console()

app = typer.Typer(
    help="ki-dev - begrenzte deterministische Agentenmaschine.",
    no_args_is_help=True,
    add_completion=False,
)
loop_app = typer.Typer(
    help="Einen ki-dev-Lauf starten oder fortsetzen.",
)
app.add_typer(loop_app, name="loop")
app.add_typer(planning_app, name="planning")
app.command("handoff")(handoff)


def main() -> None:
    app()


@loop_app.callback(invoke_without_command=True)
def loop(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
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


@loop_app.command()
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


@loop_app.command("status")
def status(
    run_id: Annotated[str, typer.Argument()],
    runs_dir: Annotated[Path, typer.Option("--runs-dir")] = Path(
        ".ki-dev/runs"
    ),
) -> None:
    """Den Status eines Laufs anzeigen, ohne ihn fortzusetzen."""
    _execute(lambda: status_run(run_id, runs_dir=runs_dir))


def _execute(action: Callable[[], LoopRunResult]) -> None:
    try:
        result = action()
    except (LoopConfigError, LoopResumeError, RunStoreError) as exc:
        _abort(str(exc))
    console.print_json(data=result_document(result))


def _abort(message: str) -> None:
    console.print(f"[red]{message}[/red]")
    raise typer.Exit(code=2)
