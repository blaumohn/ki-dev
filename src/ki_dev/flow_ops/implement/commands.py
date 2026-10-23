"""Ops des Ablaufs ``implement``: Auftrag aus dem Bead, Rollen aus dem
Profil, der Ausführer fährt den Ablauf bis zum nächsten Halt.

    ki-dev -f implement BEAD [--profile NAME] [--adapter [ROLLE=]NAME]
    ki-dev -f implement resume RUN_ID [--answer TEXT] [--adapter …]
    ki-dev -f implement status RUN_ID
    ki-dev -f implement history RUN_ID

``--adapter manual`` ersetzt die Agentensitzung durch den Menschen als
Boten: die Eingabe geht auf stdout, die formale Antwort kommt von
stdin. ``ki-dev -f ABLAUF step`` gibt dagegen zustandslos einzelne
Übergaben aus; den Befehl hat jedes Paket (Gerüst).
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
from ki_dev.flow_ops.implement.cli import (
    DEFAULT_PROFILE,
    ExecutorWrap,
    RunConfigError,
    adapter_overrides,
    load_profile,
    profile_path,
    result_document,
    resume_run,
    start_run,
    status_document,
)
from ki_dev.flow_ops.implement.history import run_history
from ki_dev.flow_ops.implement.machine import IMPLEMENT
from ki_dev.flow_ops.implement.runtime import RunResult, RunResumeError
from ki_dev.flow_ops.live import LiveExecutor
from ki_dev.flow_ops.options import ADAPTER_OPTION
from ki_dev.ops.context.bead_input import (
    BeadInput,
    BeadInputInvalidError,
    criteria_with_refs,
    validate_bead_input,
)
from ki_dev.ops.context.beads_reader import BeadsReadError, read_issue
from ki_dev.run_store import RunStore, RunStoreError

# Bead-Felder, die ein Umsetzungsauftrag braucht (wie ``require`` am
# Schreibzustand von implement_review.toml; ein Ablauf ab ige.6).
_REQUIRE = ("design", "acceptance_criteria")
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
    app.command("history")(history)
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
    adapters: ADAPTER_OPTION = None,
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
    runs_dir: RUNS_OPTION = RUNS_DIR,
    verbose: VERBOSE_OPTION = False,
) -> None:
    """Neuen Lauf für BEAD starten."""
    _progress(verbose)
    cwd = Path.cwd()

    def action() -> RunResult:
        overrides = adapter_overrides(adapters or [])
        loaded = load_profile(profile_path(profile, cwd))
        config = {
            **loaded.values,
            **_bead_task(bead_id, cwd),
            **overrides,
        }
        return start_run(
            config,
            run_id=run_id,
            runs_dir=runs_dir,
            wrap=_live(verbose),
            profile=loaded,
        )

    _execute(lambda: result_document(action()))


def resume(
    run_id: Annotated[str, typer.Argument()],
    answer: Annotated[str | None, typer.Option("--answer")] = None,
    reconcile_result: Annotated[
        Path | None, typer.Option("--reconcile-result")
    ] = None,
    adapters: ADAPTER_OPTION = None,
    runs_dir: RUNS_OPTION = RUNS_DIR,
    verbose: VERBOSE_OPTION = False,
) -> None:
    """Pausierten Lauf fortsetzen."""
    _progress(verbose)
    _execute(
        lambda: result_document(
            resume_run(
                run_id,
                runs_dir=runs_dir,
                answer=answer,
                reconcile_result=reconcile_result,
                wrap=_live(verbose),
                overrides=adapter_overrides(adapters or []),
            )
        )
    )


def status(
    run_id: Annotated[str, typer.Argument()],
    runs_dir: RUNS_OPTION = RUNS_DIR,
) -> None:
    """Status eines Laufs samt Profilnachweis zeigen, ohne ihn
    fortzusetzen."""
    _execute(lambda: status_document(run_id, runs_dir=runs_dir))


def history(
    run_id: Annotated[str, typer.Argument()],
    runs_dir: RUNS_OPTION = RUNS_DIR,
) -> None:
    """Verlauf eines Laufs lesbar zeigen: je Runde Änderungen, Tests
    und Review, danach der Abschluss."""
    try:
        lines = run_history(RunStore(runs_dir, run_id))
    except _ERRORS as exc:
        _abort(str(exc))
    for line in lines:
        print(line)


def _bead_task(bead_id: str, cwd: Path) -> dict[str, object]:
    """Auftrag, Abnahmekriterien und Quellen aus dem Bead."""
    issue = read_issue(bead_id, cwd)
    problems = validate_bead_input(issue, _REQUIRE)
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


def _execute(action: Callable[[], dict[str, object]]) -> None:
    try:
        document = action()
    except _ERRORS as exc:
        _abort(str(exc))
    console.print_json(data=document)


def _abort(message: str) -> NoReturn:
    errors.print(Text(message, style="red"))
    raise typer.Exit(code=2)
