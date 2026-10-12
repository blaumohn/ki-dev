"""Projektion des Ausführers auf den Boten (Adapter ``manual``):
was ein Aufruf im Planungsablauf tut und welche Übergabe er ausgibt."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, NamedTuple, Protocol, cast

from ki_dev.flow.model import PASS, FlowError, Transition
from ki_dev.flow.review_flow import ReviewFlow
from ki_dev.ops.checks import PREFLIGHT
from ki_dev.ops.checks.options import (
    CONTROL_SCHEMA,
    check_control,
    control_from,
)
from ki_dev.ops.checks.run import ChecksOutcome, run_checks
from ki_dev.ops.checks.stand import current_stand
from ki_dev.ops.context.bead_input import BeadInput, criteria_with_refs
from ki_dev.ops.context.beads_reader import read_issue
from ki_dev.ops.context.blocks import TurnInput
from ki_dev.ops.context.guidelines import GuidelineSection
from ki_dev.ops.context.limit_config import load_base_max_chars
from ki_dev.runner.planning import (
    FULL_CHECKS,
    TURN,
    Halt,
    MachineOperation,
    PlanningContext,
    StaleAnswerError,
    allows,
    planning_runtime,
    with_facts,
)
from ki_dev.runner.review_output import (
    AgentProtocolError,
    PlanningAnswer,
    parse_planning_answer,
)
from ki_dev.step.boundary import (
    CONSOLE,
    feedback_limit,
    progress,
    project_preflight_config,
    selected_guidelines,
)
from ki_dev.step.choices import Step
from ki_dev.step.feedback import (
    DecisionInputError,
    load_feedback_max_chars,
    read_decision,
    read_feedback,
)
from ki_dev.step.options import (
    NO_PREFLIGHT_OPTIONS,
    Inputs,
    PreflightRequest,
)
from ki_dev.step.state import SavedState, step_dir
from ki_dev.step.turn import ensure_base_fits, hand_over, require_valid

REVIEW_KIND = "review"
CORRECTION_KIND = "correction"

DONE = "done"
"""Ereignis „Schreiben bzw. Korrektur getan“ des Review-Musters:
``--step review`` beginnt mit ihm am Start des Ablaufs."""

class Output(NamedTuple):
    """Ausgabe eines Bead-Aufrufs: Text, Exitcode, Halt des Ablaufs."""

    text: str
    exit_code: int
    halt: Halt
    flow: ReviewFlow

class Run(Protocol):
    def __call__(
        self,
        state: str,
        event: str | None,
        machine: dict[str, MachineOperation],
        current: Mapping[str, str] | None = None,
        attempt: str | None = None,
        answer_file: Path | None = None,
    ) -> Halt: ...

def planner(
    bead_id: str, flow: ReviewFlow, saved: SavedState | None
) -> Run:
    """Ein Schritt des Planungs-Threads dieses Beads: wartet der Lauf
    genau in ``state``, ist ``event`` seine Antwort (resume); sonst
    beginnt der Aufruf dort (start, im Protokoll ggf. ein Sprung)."""

    def run(
        state: str,
        event: str | None,
        machine: dict[str, MachineOperation],
        current: Mapping[str, str] | None = None,
        attempt: str | None = None,
        answer_file: Path | None = None,
    ) -> Halt:
        with planning_runtime(
            flow.flow, step_dir(bead_id), bead_id, machine
        ) as runtime:
            if saved is not None and saved.state == state and event:
                if attempt is None:
                    return runtime.advance(event, current)
                return runtime.resume(
                    event,
                    current,
                    attempt,
                    (
                        None
                        if answer_file is None
                        else str(answer_file.resolve())
                    ),
                )
            return runtime.start(state, event, current)

    return run

def bead_output(
    bead_id: str,
    flow: ReviewFlow,
    step: Step,
    extra: PreflightRequest,
    next_turn: bool,
    inputs: Inputs,
    saved: SavedState | None,
) -> Output:
    """Übergabetext, Exitcode und Halt. Die Basisgrenze gilt nicht für
    ``--next-turn`` (Folgenachricht, eigener Vertrag); sonst wird sie
    vor jedem Beads-Zugriff und Vorlauf gelesen."""
    run = planner(bead_id, flow, saved)
    if step is Step.REVIEW and next_turn:
        issue = read_issue(bead_id, Path.cwd())
        if inputs.decision is not None:
            text, code, halt = decision_turn(
                issue, inputs.decision, flow, run, saved
            )
            return Output(text, code, halt, flow)
        text, code, halt = next_turn_handoff(
            issue, extra, inputs.feedback, flow, run
        )
        return Output(text, code, halt, flow)
    limit = load_base_max_chars(Path.cwd())
    issue = read_issue(bead_id, Path.cwd())
    if step is Step.REVIEW:
        guidelines = selected_guidelines(flow, review=True)
        text, code, halt = review_handoff(
            issue, extra, guidelines, limit, flow, run
        )
        return Output(text, code, halt, flow)
    start = flow.flow.start
    ensure_base_fits(flow, issue, start, limit)
    # Projektion: Der Ablauf hält im Startzustand bei seinem turn.
    halt = expect_turn(run(start, None, {}), start)
    subject = turn_input(
        issue,
        flow,
        halt,
        guidelines=selected_guidelines(flow, review=False),
    )
    text = hand_over(flow, halt.turn, subject, limit)
    return Output(text, 0, halt, flow)

def review_handoff(
    issue: BeadInput,
    extra: PreflightRequest,
    guidelines: tuple[GuidelineSection, ...],
    base_max_chars: int,
    flow: ReviewFlow,
    run: Run,
) -> tuple[str, int, Halt]:
    """Übergabe für ``--step review``, Exitcode und Halt.

    ``done`` am Start des Ablaufs; was danach geschieht, sagt der
    Ablauf. Bindet er den Vorlauf (Zustand ``P.preflight``), werden
    Bead und Konfiguration vollständig validiert, bevor der erste
    Korrekturbefehl läuft, und die Kante aus dem Vorlauf wählt die
    Nachricht: Review-Übergabe oder, bei checks_failed, die
    Reparaturnachricht an den Umsetzer (Exit 1). Ohne Bindung ist das
    Review eine reine Quellenprüfung ohne Prozessaufrufe. Die
    Basisgrenze wird vorher geprüft, denn Korrekturen können Dateien
    ändern.
    """
    ensure_base_fits(
        flow, issue, flow.state_of(REVIEW_KIND), base_max_chars
    )
    halt = run(flow.flow.start, DONE, machine_operations(extra, issue))
    subject = turn_input(
        issue, flow, halt, guidelines=guidelines
    )
    text = hand_over(flow, halt.turn, subject, base_max_chars)
    return text, exit_code(subject), halt

def machine_operations(
    extra: PreflightRequest,
    issue: BeadInput,
    exclude: Path | None = None,
) -> dict[str, MachineOperation]:
    """Maschinenoperationen des Planungsablaufs für den Ausführer:
    checks ist der deterministische Vorlauf dieses Projekts; danach
    gilt der Stand (Arbeitsbaum, Bead), auf dem er lief."""

    def checks(
        _state: str, context: PlanningContext
    ) -> tuple[str, PlanningContext]:
        outcome = run_checks(
            Path.cwd(), extra.extra, extra.skip, progress
        )
        partial = outcome.report is not None and outcome.report.partial
        facts = frozenset() if partial else frozenset({FULL_CHECKS})
        excluded = exclude
        if excluded is None and context.answer_file is not None:
            excluded = Path(context.answer_file)
        checked = current_stand(Path.cwd(), issue, exclude=excluded)
        return outcome.event, with_facts(
            context, facts, outcome, checked
        )

    return {PREFLIGHT: checks}

def turn_input(
    issue: BeadInput,
    flow: ReviewFlow,
    halt: Halt,
    **extra: Any,
) -> TurnInput:
    """Eingabe der Übergabe dieses Halts: Ergebnis des Vorlaufs (wenn
    einer lief), Zustand der Folgeschritte und der Wächter-Befund zu
    PASS; welche Teile eine Übergabe nutzt, sagt der Ablauf."""
    outcome = cast(ChecksOutcome | None, halt.context.outcome)
    failure = None if outcome is None else outcome.failure
    limit = None if failure is None else feedback_limit()
    return replace(
        TurnInput(
            issue,
            flow.flow,
            halt.state,
            report=None if outcome is None else outcome.report,
            finding=failure,
            feedback_limit=limit,
            pass_allowed=pass_allowed(flow, halt),
            attempt=halt.attempt,
        ),
        **extra,
    )

def exit_code(subject: TurnInput) -> int:
    """Ein fehlgeschlagener Vorlauf (Reparaturnachricht) endet mit 1."""
    return 0 if subject.finding is None else 1

def expect_turn(halt: Halt, state: str) -> Halt:
    """step projiziert genau bis zum nächsten turn; alles andere wäre
    ein Widerspruch zwischen Ablauf und Aufruf (Programmfehler)."""
    if (halt.state, halt.operation) != (state, TURN):
        raise FlowError(
            f"Ablauf hält in {halt.state} ({halt.operation}), "
            f"erwartet {state} (turn)"
        )
    return halt

def next_turn_handoff(
    issue: BeadInput,
    extra: PreflightRequest,
    feedback_file: str | None,
    flow: ReviewFlow,
    run: Run,
) -> tuple[str, int, Halt]:
    """Nächste Nachricht nach einer Korrektur, Exitcode und Halt.

    Alle Eingaben (Bead, Grenze, Rückmeldung) sind geprüft, bevor der
    Vorlauf startet. ``done`` an der Korrektur; bindet der Ablauf den
    Vorlauf, folgt er: Fehlschlag -> Umsetzer (Exit 1, Nachricht auf
    stdout), Erfolg -> Reviewer; sonst geht es direkt zur erneuten
    Review-Übergabe. Die Grenze wird für jeden Ablauf gelesen und
    geprüft (ungültiges TOML oder ein ungültiger Wert wird
    abgelehnt); eine fehlende Vorlauf-Konfiguration bleibt ohne
    Bindung erlaubt.
    """
    require_valid(issue, flow, flow.state_of(REVIEW_KIND))
    limit = load_feedback_max_chars(Path.cwd())
    feedback = None
    if feedback_file is not None:
        feedback = read_feedback(feedback_file, limit, CONSOLE)
    halt = run(
        flow.state_of(CORRECTION_KIND),
        DONE,
        machine_operations(extra, issue),
    )
    return after_preflight(issue, feedback, flow, halt)

def pass_allowed(flow: ReviewFlow, halt: Halt) -> bool:
    """Ob der Ablauf im erreichten Review PASS zulässt (Wächter)."""
    return allows(flow.flow, halt.state, PASS, halt.context)

def decision_turn(
    issue: BeadInput,
    source: str,
    flow: ReviewFlow,
    run: Run,
    saved: SavedState | None,
) -> tuple[str, int, Halt]:
    """Reviewer-Antwort prüfen und Nachricht laut Tabelle; der Bead
    muss den Umsetzungsvertrag erfüllen (Abnahmekriterien). Die
    Wächter sehen den gespeicherten Laufzustand: nach einem Teillauf
    weist der Ablauf PASS ab. Die Antwort bringt den aktuellen Stand
    mit; hat er sich seit dem Vorlauf geändert, führt PASS zurück in
    den Vorlauf und die nächste Nachricht geht an das Review."""
    review = flow.state_of(REVIEW_KIND)
    require_valid(issue, flow, review)
    raw = read_decision(source, CONSOLE)
    answer = parse_answer(raw, issue, flow)
    # Die Antwort gilt nur dort, wo der Lauf auf sie wartet: ohne
    # Vorlauf gibt es keine Review-Übergabe, nach einem roten Vorlauf
    # (implement.correction) ist ein PASS kein Ausweg.
    if saved is None:
        raise DecisionInputError(
            "Review-Antwort ungültig: kein Vorlauf in diesem Lauf; "
            f"zuerst `ki-dev step {issue.id} --step review`"
        )
    if (saved.flow, saved.state) != (flow.flow.name, review):
        raise DecisionInputError(
            f"Review-Antwort ungültig: der Lauf wartet in "
            f"{saved.state}, nicht in {review}"
        )
    answer_file = None if source == "-" else Path(source)
    current = current_stand(Path.cwd(), issue, exclude=answer_file)
    if current is None and answer.verdict.event == PASS:
        raise DecisionInputError(
            "Review-Antwort ungültig: PASS braucht einen geprüften "
            "Stand, und den gibt es nur in einem Git-Arbeitsverzeichnis"
        )
    machine = machine_operations(
        NO_PREFLIGHT_OPTIONS, issue, exclude=answer_file
    )
    # Das gebundene Ereignis nimmt die Kante aus implement.review.
    try:
        halt = run(
            review,
            answer.verdict.event,
            machine,
            current,
            answer.attempt,
            answer_file,
        )
    except StaleAnswerError as exc:
        raise DecisionInputError(
            f"Review-Antwort ungültig: {exc}"
        ) from exc
    except FlowError as exc:
        raise DecisionInputError(
            f"Review-Antwort ungültig: {exc} (Teillauf: kein PASS)"
        ) from exc
    if not changed_since_preflight(flow, halt):
        answered = cast(Transition, halt.entry)
        args, skip = control_from(answer.extras)
        subject = replace(
            turn_input(issue, flow, halt),
            state=answered.source,
            events=(answered.event,),
            verdict=answer.verdict,
            preflight_args=args,
            preflight_skip=skip,
        )
        return hand_over(flow, halt.turn, subject), 0, halt
    progress(
        "Stand seit dem Vorlauf geändert (Arbeitsbaum oder Bead): "
        "PASS nicht angenommen, neuer Vorlauf"
    )
    return after_preflight(issue, None, flow, halt)

def parse_answer(
    raw: str, issue: BeadInput, flow: ReviewFlow
) -> PlanningAnswer:
    """Antwort prüfen und an die Abnahmekriterien binden; die
    Steuerfelder prüft die Operation ``checks`` (eingesteckt)."""
    refs = [ref for ref, _ in criteria_with_refs(issue)]
    try:
        return parse_planning_answer(
            raw,
            flow.flow,
            refs,
            CONTROL_SCHEMA,
            partial(
                check_control, load_config=project_preflight_config
            ),
        )
    except AgentProtocolError as exc:
        raise DecisionInputError(
            f"Review-Antwort ungültig: {exc}"
        ) from exc

def changed_since_preflight(flow: ReviewFlow, halt: Halt) -> bool:
    """Die Antwort nahm die Kante zurück in den Vorlauf."""
    entry = halt.entry
    return (
        entry is not None
        and flow.flow.state(entry.target).kind == "machine"
    )

def after_preflight(
    issue: BeadInput,
    feedback: str | None,
    flow: ReviewFlow,
    halt: Halt,
) -> tuple[str, int, Halt]:
    """Nachricht nach der Korrektur oder nach einem neuen Vorlauf:
    die Übergabe des Halts laut Ablauf (Reparatur an den Umsetzer mit
    Exit 1 oder Folgerunde an das Review)."""
    subject = turn_input(issue, flow, halt, feedback=feedback)
    text = hand_over(flow, halt.turn, subject)
    return text, exit_code(subject), halt
