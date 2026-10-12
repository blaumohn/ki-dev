"""Felder und Kontextbausteine der Übergaben des Planungsablaufs.

Der Ablauf (z. B. ``map.toml``) deklariert je Übergabe eine Vorlage und
die Kontextbausteine in ihrer Reihenfolge. Was ein Platzhalter der
Vorlage (:data:`FIELDS`) und was ein Baustein (:data:`BLOCKS`) unter
seinem Namen liefert, steht hier; der Aufrufer steckt beides in den
Ausführer (``runner.turns``). Beide erhalten dieselbe Eingabe,
:class:`TurnInput`.
"""

from __future__ import annotations

import shlex
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from ki_dev.flow.model import FlowError, Turn
from ki_dev.flow.review_flow import TEMPLATES, ReviewFlow
from ki_dev.flow.templates import lines as lines_of
from ki_dev.flow.templates import render, text
from ki_dev.ops.checks.options import ARGS_OPTION, SKIP_OPTION
from ki_dev.ops.checks.preflight import (
    PreflightReport,
    artifact_line,
    format_command_result,
)
from ki_dev.ops.context.bead_input import BeadInput, criterion_line
from ki_dev.ops.context.contract import one_line
from ki_dev.ops.context.guidelines import (
    GuidelineSection,
    guideline_lines,
)
from ki_dev.review_decision import ReviewVerdict

OUTSIDE_BASE = frozenset({"report", "attempt", "guidelines"})
"""Bausteine, die nicht zur Basis der Übergabe zählen (Basisgrenze)."""


@dataclass(frozen=True)
class TurnInput:
    """Alles, was Felder und Bausteine einer Übergabe brauchen.

    ``state`` und ``events`` wählen die Folgeschritte: die Kanten, die
    aus ``state`` führen, bei ``events`` nur die dieser Ereignisse."""

    issue: BeadInput
    flow: ReviewFlow
    state: str
    events: tuple[str, ...] | None = None
    guidelines: Sequence[GuidelineSection] = ()
    reading_hint: str | None = None
    report: PreflightReport | None = None
    feedback: str | None = None
    feedback_limit: int | None = None
    finding: str | None = None
    pass_allowed: bool = True
    attempt: str | None = None
    verdict: ReviewVerdict | None = None
    preflight_args: Mapping[str, str] = field(default_factory=dict)
    preflight_skip: Mapping[str, str] = field(default_factory=dict)


# --- Felder -----------------------------------------------------------


def _bead(turn: TurnInput) -> str:
    issue = turn.issue
    return f"{one_line(issue.id)} - {one_line(issue.title)}"


def _output(turn: TurnInput) -> str:
    name = "verdict" if turn.pass_allowed else "verdict-partial"
    return text(TEMPLATES, name)


def _verdict(turn: TurnInput) -> ReviewVerdict:
    if turn.verdict is None:
        raise FlowError("Übergabe braucht ein Urteil (verdict)")
    return turn.verdict


def _judgement(turn: TurnInput) -> str:
    return turn.flow.flow.verdict(_verdict(turn).event).value


def _detail(turn: TurnInput) -> str:
    return one_line(_verdict(turn).detail)


FIELDS: dict[str, Callable[[TurnInput], object]] = {
    "bead": _bead,
    "common": lambda _turn: text(TEMPLATES, "common"),
    "rules": lambda _turn: text(TEMPLATES, "review-rules"),
    "output": _output,
    "limit": lambda turn: turn.feedback_limit,
    "event": lambda turn: _verdict(turn).event,
    "judgement": _judgement,
    "ref": lambda turn: _verdict(turn).requirement_ref,
    "detail": _detail,
    "reason": lambda turn: _detail(turn) or "ohne Begründung",
}
"""Platzhalter der Vorlagen, je Name aus der Vorlage."""


# --- Bausteine --------------------------------------------------------


def _finding_classes(turn: TurnInput) -> list[str]:
    """Schließt ohne Leerzeile an die Rollenvorlage an."""
    return list(turn.flow.class_lines())


def _epic_sections(turn: TurnInput) -> list[str]:
    if not turn.issue.epic_context:
        return []
    lines = ["", *lines_of(TEMPLATES, "epic-intro")]
    for epic_id, epic_context in turn.issue.epic_context:
        lines += [
            "",
            render(
                TEMPLATES,
                "epic-hint",
                id=one_line(epic_id),
                context=one_line(epic_context),
            ),
        ]
    return lines


def _source_refs(turn: TurnInput) -> list[str]:
    return [
        "",
        "Quellenreferenzen (unaufgelöst):",
        *(f"- {one_line(ref)}" for ref in turn.issue.source_refs),
    ]


def _criteria(turn: TurnInput) -> list[str]:
    return ["", criterion_line(turn.issue)]


def _next_steps(turn: TurnInput) -> list[str]:
    """Folgeschritte laut Ablauf als abschließender Block."""
    return [
        "",
        *turn.flow.hint_lines(
            turn.state, one_line(turn.issue.id), turn.events
        ),
    ]


def _attempt(turn: TurnInput) -> list[str]:
    """Kennung des Versuchs, für den diese Übergabe ausgegeben wird;
    eine Antwort trägt sie zurück. Leer, wenn nichts wartet."""
    if turn.attempt is None:
        return []
    return [render(TEMPLATES, "attempt-line", attempt=turn.attempt)]


def _reading_hint(turn: TurnInput) -> list[str]:
    if turn.reading_hint is None:
        return []
    return ["", turn.reading_hint]


def _report(turn: TurnInput) -> list[str]:
    """Kompakter Vorlaufbericht (``PRUEFBERICHT …``); leer ohne
    Vorlauf (Prüfgegenstände ohne Code)."""
    report = turn.report
    if report is None:
        return []
    lines = [f"PRUEFBERICHT vorlauf-start={report.started_at}"]
    lines += [format_command_result(item) for item in report.commands]
    lines.append(artifact_line(report))
    if report.partial:
        lines.append(text(TEMPLATES, "partial-run-note"))
    lines.append(text(TEMPLATES, "pass-note"))
    return lines


def _report_followup(turn: TurnInput) -> list[str]:
    report = _report(turn)
    return ["", *report] if report else []


def _guidelines(turn: TurnInput) -> list[str]:
    return guideline_lines(turn.guidelines)


def _feedback(header: str) -> Callable[[TurnInput], list[str]]:
    def lines(turn: TurnInput) -> list[str]:
        if turn.feedback is None:
            return []
        quoted = [
            f"| {_quoted(line)}".rstrip()
            for line in turn.feedback.splitlines()
        ]
        return ["", text(TEMPLATES, header), *quoted]

    return lines


def _quoted(line: str) -> str:
    """Zeile der Rückmeldung ohne Steuerzeichen (auch ANSI-Escapes);
    Leerraum bleibt Zeichen für Zeichen erhalten, es wird nur an den
    Enden gekürzt: Nutzertext bleibt erkennbar."""
    return "".join(
        " " if ch.isspace() else ch
        for ch in line
        if ch.isprintable() or ch.isspace()
    ).strip()


def _human_note(_turn: TurnInput) -> list[str]:
    return ["", text(TEMPLATES, "human-note")]


def _finding(turn: TurnInput) -> list[str]:
    if turn.finding is None:
        raise FlowError("Übergabe braucht einen Befund (finding)")
    return ["", turn.finding]


def _control(turn: TurnInput) -> list[str]:
    """Vorgeschlagene Prüfsteuerung als ausführbarer Befehl."""
    if not (turn.preflight_args or turn.preflight_skip):
        return []
    argv = [
        "ki-dev",
        "step",
        one_line(turn.issue.id),
        "--step",
        "review",
        "--next-turn",
    ]
    for option, values in (
        (ARGS_OPTION, turn.preflight_args),
        (SKIP_OPTION, turn.preflight_skip),
    ):
        for name, value in values.items():
            argv += [option, f"{name}={value}"]
    return ["", text(TEMPLATES, "control-intro"), shlex.join(argv)]


BLOCKS: dict[str, Callable[[TurnInput], Sequence[str]]] = {
    "finding_classes": _finding_classes,
    "epic_sections": _epic_sections,
    "source_refs": _source_refs,
    "criteria": _criteria,
    "next_steps": _next_steps,
    "attempt": _attempt,
    "reading_hint": _reading_hint,
    "report": _report,
    "report_followup": _report_followup,
    "guidelines": _guidelines,
    "feedback_review": _feedback("feedback-header-review"),
    "feedback_repair": _feedback("feedback-header"),
    "human_note": _human_note,
    "finding": _finding,
    "control": _control,
}
"""Kontextbausteine, je Name aus dem Vokabular des Ablaufs."""


# --- Zuordnung Schritt → Übergabe -------------------------------------


def state_turn(flow: ReviewFlow, state: str) -> Turn:
    """Die Übergabe des Zustands laut Ablauf: Vorlage und Kontext."""
    for operation in flow.flow.state(state).operations:
        if operation.turn is not None:
            return operation.turn
    raise FlowError(f"{flow.file}: {state} hat keine Übergabevorlage")


# --- Basisgrenze ------------------------------------------------------


def base_fields(
    turn: TurnInput, context: Sequence[str]
) -> list[tuple[str, int]]:
    """Zeichenanteile der veränderlichen Basisteile, ohne Rohwerte;
    welche Teile vorkommen, sagt der Kontext der Übergabe."""
    issue = turn.issue
    fields = [
        ("id", len(one_line(issue.id))),
        ("title", len(one_line(issue.title))),
    ]
    for index, (epic_id, epic) in enumerate(issue.epic_context):
        size = len(one_line(epic_id)) + len(one_line(epic))
        fields.append((f"epic_context[{index}]", size))
    if "source_refs" in context:
        for index, ref in enumerate(issue.source_refs):
            fields.append((f"source_refs[{index}]", len(one_line(ref))))
    if "criteria" in context:
        size = len(criterion_line(issue))
        fields.append(("acceptance_criteria", size))
    if turn.reading_hint is not None:
        fields.append(("Lesehinweis", len(turn.reading_hint)))
    return fields
