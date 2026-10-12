"""I/O-Grenze von ``ki-dev step``: Ablauf, Grenzen, Leitlinien
und Transport des Boten laden; Fehler werden zu Exitcodes."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import BinaryIO, NoReturn

import typer

from ki_dev.adapter.manual import Console
from ki_dev.flow.model import FlowError
from ki_dev.flow.review_flow import ReviewFlow, load_review_flow
from ki_dev.ops.checks.preflight import (
    PreflightConfig,
    load_preflight_config,
)
from ki_dev.ops.context.guidelines import (
    GuidelineContractError,
    GuidelineDocument,
    GuidelineSection,
    select_guidelines,
)
from ki_dev.ops.context.guidelines_source import (
    GuidelineSourceError,
    load_guidelines,
)
from ki_dev.ops.context.limit_config import (
    LimitConfigInvalidError,
    LimitConfigReadError,
    load_base_max_chars,
)
from ki_dev.step.exits import fail
from ki_dev.step.feedback import load_feedback_max_chars
from ki_dev.step.turn import bind_flow


def bound_flow(name: str) -> ReviewFlow:
    """step-Ablauf an der I/O-Grenze laden und an die eingesteckten
    Felder und Kontextbausteine binden; ein ungültiger mitgelieferter
    Ablauf ist ein Programmfehler (Exit 1)."""
    try:
        flow = load_review_flow(name)
        bind_flow(flow)
        return flow
    except FlowError as exc:
        fail(f"Ablauf {name} ungültig: {exc}", code=1)

def base_limit() -> int:
    """Basisgrenze vor jeder Schreibwirkung lesen (Exit 2 ungültig,
    Exit 1 nicht lesbar)."""
    try:
        return load_base_max_chars(Path.cwd())
    except LimitConfigInvalidError as exc:
        fail(str(exc), code=2)
    except LimitConfigReadError as exc:
        fail(str(exc), code=1)

def selected_guidelines(
    flow: ReviewFlow, review: bool
) -> tuple[GuidelineSection, ...]:
    """Leitlinien vor Vorlauf und Schreibwirkungen laden und für die
    Phase des Ablaufs (sein Start) auswählen."""
    try:
        return select_guidelines(
            guideline_documents(), flow.flow.start, review
        )
    except GuidelineContractError as exc:
        _contract_failure(exc)

def guideline_documents() -> tuple[GuidelineDocument, ...]:
    """Quellen laden. Fehlend/unlesbar: Exit 1; kein UTF-8, ungültiges
    YAML oder Vertragsverletzung: Exit 2. Diagnosen nennen Datei,
    Feldpfad und ggf. Zeile, nie Regeltexte.
    """
    try:
        return load_guidelines(Path.cwd())
    except GuidelineSourceError as exc:
        fail(f"Leitlinienquelle nicht lesbar: {exc}", code=1)
    except GuidelineContractError as exc:
        _contract_failure(exc)

def _contract_failure(exc: GuidelineContractError) -> NoReturn:
    problems = "\n".join(f"  {problem}" for problem in exc.problems)
    fail(
        f"Leitlinienquelle ungültig: {exc.source}\n{problems}",
        code=2,
    )

def feedback_limit() -> int:
    return load_feedback_max_chars(Path.cwd())

def project_preflight_config() -> PreflightConfig:
    """Nur bei Steuerfeldern geladen; Fehler bleiben Exit 2."""
    return load_preflight_config(Path.cwd())

def stdin_binary() -> BinaryIO:
    return sys.stdin.buffer

"""Transport des Boten für step: Eingabe auf stdout, Antwort aus Datei
oder stdin."""

CONSOLE = Console(
    lambda text: typer.echo(text, nl=False), lambda: stdin_binary()
)

def progress(line: str) -> None:
    # stderr: stdout trägt nur die Übergabe (``> uebergabe.txt``).
    typer.echo(line, err=True)
