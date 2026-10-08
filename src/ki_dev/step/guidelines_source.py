"""Leitlinienquellen lesen (UTF-8/YAML) und Markdown-Seiten abgleichen.

Ein-/Ausgabegrenze zu ``handoff_guidelines``: liest die festen YAML-
Dateien relativ zur Projektwurzel, ohne Ersatzquelle, und übersetzt
Lese- und Parsefehler in bereinigte Diagnosen ohne Rohinhalte.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import yaml

from ki_dev.step.guidelines import (
    GUIDELINE_SOURCES,
    GuidelineContractError,
    GuidelineDocument,
    GuidelineSource,
    parse_guideline_document,
    render_guideline_documents,
)


class GuidelineSourceError(RuntimeError):
    """Leitlinienquelle fehlt oder ist nicht lesbar."""


def load_guidelines(
    project_root: Path,
) -> tuple[GuidelineDocument, ...]:
    """Beide Quellen in fester Reihenfolge laden und prüfen.

    Fehlend/unlesbar: ``GuidelineSourceError``; kein UTF-8, ungültiges
    YAML oder Vertragsverletzung: ``GuidelineContractError``.
    """
    return tuple(
        parse_guideline_document(
            source, _read_yaml(project_root, source)
        )
        for source in GUIDELINE_SOURCES
    )


def _read_yaml(project_root: Path, source: GuidelineSource) -> object:
    try:
        raw = (project_root / source.path).read_bytes()
    except OSError as exc:
        raise GuidelineSourceError(
            f"{source.path}: nicht lesbar ({type(exc).__name__})"
        ) from None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise GuidelineContractError(
            source.path, ("kein gültiges UTF-8",)
        ) from None
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise GuidelineContractError(
            source.path, (_yaml_diagnosis(exc),)
        ) from None


def _yaml_diagnosis(exc: yaml.YAMLError) -> str:
    """Nur Position; problem/context der Ausnahme enthalten Rohtext."""
    mark = getattr(exc, "problem_mark", None)
    if mark is None:
        return "ungültiges YAML"
    line, column = mark.line + 1, mark.column + 1
    return f"ungültiges YAML (Zeile {line}, Spalte {column})"


def sync_guideline_documents(
    project_root: Path, *, check: bool
) -> tuple[PurePosixPath, ...]:
    """Markdown-Seiten aus den Quellen erzeugen.

    Gibt die abweichenden Seiten zurück; schreibt sie nur ohne
    ``check``.
    """
    rendered = render_guideline_documents(load_guidelines(project_root))
    drift = tuple(
        path
        for path, text in rendered.items()
        if _current(project_root / path) != text
    )
    if not check:
        for path in drift:
            (project_root / path).write_text(
                rendered[path], encoding="utf-8"
            )
    return drift


def _current(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
