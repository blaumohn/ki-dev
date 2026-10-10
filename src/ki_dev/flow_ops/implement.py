"""Ops des Ablaufs ``implement``: Auftrag aus dem Bead, Rollen aus dem
Profil, der Ausführer fährt den Ablauf bis zum nächsten Halt.

    ki-dev -f implement BEAD [--profile NAME] [--adapter [ROLLE=]NAME]
    ki-dev -f implement resume RUN_ID [--answer TEXT]
    ki-dev -f implement status RUN_ID

``--adapter manual`` ersetzt die Agentensitzung durch den Menschen als
Boten: die Eingabe geht auf stdout, die formale Antwort kommt von
stdin. Der frühere Befehl ``ki-dev step`` ist damit nur noch ein
Adapter, kein eigener Ablauf.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, NoReturn, cast

import typer
from rich.console import Console
from rich.text import Text

from ki_dev.adapter.executors import Executor
from ki_dev.flow.model import Flow, FlowError
from ki_dev.flow.templates import render, text
from ki_dev.flow_ops.live import LiveExecutor
from ki_dev.ops.context.bead_input import (
    BeadInput,
    BeadInputInvalidError,
    criteria_with_refs,
    validate_bead_input,
)
from ki_dev.ops.context.beads_reader import BeadsReadError, read_issue
from ki_dev.ops.context.contract import Step
from ki_dev.run_store import RunStoreError
from ki_dev.runner.cli import (
    DEFAULT_PROFILE,
    ExecutorWrap,
    RunConfigError,
    load_profile,
    profile_path,
    result_document,
    resume_run,
    sessionless_executors,
    start_run,
    status_run,
)
from ki_dev.runner.machine import IMPLEMENT
from ki_dev.runner.runtime import RunResult, RunResumeError

ROLES = ("worker", "review")
_ERRORS = (
    RunConfigError,
    RunResumeError,
    RunStoreError,
    BeadsReadError,
    BeadInputInvalidError,
    FlowError,
)

console = Console()
errors = Console(stderr=True)
RUNS_OPTION = Annotated[Path, typer.Option("--runs-dir")]
VERBOSE_OPTION = Annotated[
    bool,
    typer.Option(
        "--verbose",
        "-v",
        help="Zustandswechsel, Agentenaufrufe und laufende "
        "Agentenausgabe mit Token-Zähler live nach stderr.",
    ),
]
RUNS_DIR = Path(".ki-dev/runs")


def commands(flow: Flow, path: Path) -> typer.Typer:
    """Befehle des Pakets; der Ausführer bindet bisher genau den
    mitgelieferten Ablauf, eine abweichende Datei wird abgewiesen."""
    if flow != IMPLEMENT:
        raise FlowError(
            f"{path}: weicht vom mitgelieferten implement.toml ab; "
            "der Ausführer bindet bisher nur diesen"
        )
    app = typer.Typer(
        help=f"Ablauf implement ({path}) bis zum nächsten Halt fahren.",
        no_args_is_help=True,
        add_completion=False,
    )
    app.command("start")(start)
    app.command("resume")(resume)
    app.command("status")(status)
    return app


def start(
    bead_id: Annotated[str, typer.Argument(metavar="BEAD")],
    profile: Annotated[
        str,
        typer.Option(
            "--profile",
            help="NAME (.ki-dev/profiles/NAME.toml) oder Pfad.",
        ),
    ] = DEFAULT_PROFILE,
    adapters: Annotated[
        list[str] | None,
        typer.Option(
            "--adapter",
            metavar="[ROLLE=]NAME",
            help="Executor je Rolle (worker, review) ersetzen; ohne "
            "Rolle beide. NAME: ein Executor ohne Sitzungsangaben, "
            "z. B. manual (stdout/stdin), inbox oder mock.",
        ),
    ] = None,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    runs_dir: RUNS_OPTION = RUNS_DIR,
    verbose: VERBOSE_OPTION = False,
) -> None:
    """Neuen Lauf für BEAD starten."""
    _progress(verbose)
    cwd = Path.cwd()

    def action() -> RunResult:
        config = load_profile(profile_path(profile, cwd))
        config.update(_bead_task(bead_id, cwd))
        for role, adapter in _overrides(adapters or []):
            config[role] = {"executor": adapter}
        return start_run(
            config,
            run_id=run_id,
            runs_dir=runs_dir,
            wrap=_live(verbose),
        )

    _execute(action)


def resume(
    run_id: Annotated[str, typer.Argument()],
    answer: Annotated[str | None, typer.Option("--answer")] = None,
    reconcile_result: Annotated[
        Path | None, typer.Option("--reconcile-result")
    ] = None,
    runs_dir: RUNS_OPTION = RUNS_DIR,
    verbose: VERBOSE_OPTION = False,
) -> None:
    """Pausierten Lauf fortsetzen."""
    _progress(verbose)
    _execute(
        lambda: resume_run(
            run_id,
            runs_dir=runs_dir,
            answer=answer,
            reconcile_result=reconcile_result,
            wrap=_live(verbose),
        )
    )


def status(
    run_id: Annotated[str, typer.Argument()],
    runs_dir: RUNS_OPTION = RUNS_DIR,
) -> None:
    """Status eines Laufs zeigen, ohne ihn fortzusetzen."""
    _execute(lambda: status_run(run_id, runs_dir=runs_dir))


def _bead_task(bead_id: str, cwd: Path) -> dict[str, object]:
    """Auftrag, Abnahmekriterien und Quellen aus dem Bead."""
    issue = read_issue(bead_id, cwd)
    problems = validate_bead_input(issue, Step.IMPLEMENT)
    if problems:
        raise BeadInputInvalidError(problems)
    refs = issue.source_refs
    if not isinstance(refs, list):
        refs = []
    return {
        "task": _task_text(issue),
        "acceptance_criteria": [
            criterion for _, criterion in criteria_with_refs(issue)
        ],
        "sources": [f"bd:{bead_id}", *refs],
    }


def _task_text(issue: BeadInput) -> str:
    epics = ""
    if issue.epic_context:
        epics = text("implement", "bead-epics") + "".join(
            f"\n- {parent}: {hint}"
            for parent, hint in issue.epic_context
        )
    return render(
        "implement",
        "bead-task",
        id=issue.id,
        title=issue.title,
        description=issue.description,
        design=issue.design,
        epics=epics,
    )


def _overrides(values: list[str]) -> list[tuple[str, str]]:
    allowed = sessionless_executors()
    result: list[tuple[str, str]] = []
    for value in values:
        role, _, adapter = value.rpartition("=")
        if adapter not in allowed:
            raise RunConfigError(
                f"--adapter {value}: per Argument nur "
                f"{', '.join(allowed)}; Executoren mit Sitzung "
                "im Profil festlegen"
            )
        if role and role not in ROLES:
            raise RunConfigError(
                f"--adapter {value}: Rolle {', '.join(ROLES)}"
            )
        roles = (role,) if role else ROLES
        result += [(item, adapter) for item in roles]
    return result


def _live(verbose: bool) -> ExecutorWrap:
    """Mit ``--verbose`` zeigt jede Agentenrolle ihren Turn live."""
    if not verbose:
        return lambda executor, _role: executor
    return lambda executor, role: cast(
        Executor, LiveExecutor(executor, role, errors)
    )


def _progress(verbose: bool) -> None:
    if not verbose:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S")
    )
    logger = logging.getLogger("ki_dev.run")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def _execute(action: Callable[[], RunResult]) -> None:
    try:
        result = action()
    except _ERRORS as exc:
        _abort(str(exc))
    console.print_json(data=result_document(result))


def _abort(message: str) -> NoReturn:
    errors.print(Text(message, style="red"))
    raise typer.Exit(code=2)
