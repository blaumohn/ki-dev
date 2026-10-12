"""Projektion des Ausführers auf den Boten (Adapter ``manual``):
was ein Aufruf im Planungsablauf tut und welche Übergabe er ausgibt."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any, NamedTuple, Protocol, cast

from ki_dev.flow.model import PASS, FlowError, Transition
from ki_dev.flow.planning import PlanningFlow
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
from ki_dev.ops.context.contract import ReviewTarget, Step
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
    planning_flow,
    progress,
    project_preflight_config,
    selected_guidelines,
)
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

IMPLEMENT = "implement"

IMPLEMENT_REVIEW = "implement.review"

DONE = "done"

class Output(NamedTuple):
    """Ausgabe eines Bead-Aufrufs: Text, Exitcode, Halt des Ablaufs."""

    text: str
    exit_code: int
    halt: Halt
    flow: PlanningFlow

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
    bead_id: str, flow: PlanningFlow, saved: SavedState | None
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
    step: Step,
    review_of: ReviewTarget | None,
    extra: PreflightRequest,
    next_turn: bool,
    inputs: Inputs,
    saved: SavedState | None,
) -> Output:
    """Übergabetext, Exitcode und Halt. Die Basisgrenze gilt nicht für
    ``--next-turn`` (Folgenachricht, eigener Vertrag); sonst wird sie
    vor jedem Beads-Zugriff und Vorlauf gelesen."""
    flow = planning_flow()
    run = planner(bead_id, flow, saved)
    if step is Step.REVIEW and next_turn:
        issue = read_issue(bead_id, Path.cwd())
        if inputs.decision is not None:
            text, code, halt = decision_turn(
                issue, inputs.decision, flow, run, saved
            )
            return Output(text, code, halt, flow)
        text, code, halt = next_turn_handoff(
            issue, review_of, extra, inputs.feedback, flow, run
        )
        return Output(text, code, halt, flow)
    limit = load_base_max_chars(Path.cwd())
    issue = read_issue(bead_id, Path.cwd())
    if step is Step.REVIEW:
        guidelines = selected_guidelines(step, review_of)
        text, code, halt = review_handoff(
            issue, review_of, extra, guidelines, limit, flow, run
        )
        return Output(text, code, halt, flow)
    ensure_base_fits(flow, issue, step, None, limit)
    # Projektion: Der Ablauf hält im Zustand der Phase bei ihrem turn.
    halt = expect_turn(run(step.value, None, {}), step.value)
    subject = turn_input(
        issue,
        flow,
        halt,
        guidelines=selected_guidelines(step, None),
    )
    text = hand_over(flow, halt.turn, subject, limit)
    return Output(text, 0, halt, flow)

def review_handoff(
    issue: BeadInput,
    review_of: ReviewTarget | None,
    extra: PreflightRequest,
    guidelines: tuple[GuidelineSection, ...],
    base_max_chars: int,
    flow: PlanningFlow,
    run: Run,
) -> tuple[str, int, Halt]:
    """Übergabe für ``--step review``, Exitcode und Halt.

    Nur für den (Standard- oder ausdrücklichen) Prüfgegenstand implement
    läuft der deterministische Vorlauf (Zustand implement.preflight):
    Bead und Konfiguration werden vollständig validiert, bevor der
    erste Korrekturbefehl läuft (kein Schreibeffekt vor dieser
    Prüfung). Die Kante aus implement.preflight wählt die Nachricht:
    Review-Übergabe oder, bei checks_failed, die Reparaturnachricht an
    den Umsetzer (Exit 1). Für
    map/graph/materialize ist das Review eine reine Quellenprüfung:
    kein Vorlauf, keine Vorlauf-Konfiguration, keine Prozessaufrufe.
    Die Basisgrenze wird vor dem Vorlauf geprüft, denn Korrekturen
    können Dateien ändern.
    """
    if review_of not in (None, ReviewTarget.IMPLEMENT):
        target = cast(ReviewTarget, review_of)
        ensure_base_fits(
            flow, issue, Step.REVIEW, target, base_max_chars
        )
        halt = expect_turn(
            run(target.value, DONE, {}),
            f"{target.value}.review",
        )
        subject = turn_input(
            issue, flow, halt, guidelines=guidelines
        )
        text = hand_over(flow, halt.turn, subject, base_max_chars)
        return text, 0, halt
    ensure_base_fits(
        flow, issue, Step.REVIEW, review_of, base_max_chars
    )
    halt = run(IMPLEMENT, DONE, machine_operations(extra, issue))
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
    flow: PlanningFlow,
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
            flow,
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
    review_of: ReviewTarget | None,
    extra: PreflightRequest,
    feedback_file: str | None,
    flow: PlanningFlow,
    run: Run,
) -> tuple[str, int, Halt]:
    """Nächste Nachricht nach einer Korrektur, Exitcode und Halt.

    Alle Eingaben (Bead, Grenze, Rückmeldung) sind geprüft, bevor der
    Vorlauf startet. Nur der Prüfgegenstand implement läuft durch den
    Vorlauf: Fehlschlag -> Umsetzer (Exit 1, Nachricht auf stdout),
    Erfolg -> Reviewer. map/graph/materialize gehen ohne Vorlauf zur
    erneuten Review-Übergabe. Die Grenze wird für jedes Ziel gelesen
    und geprüft (ungültiges TOML oder ein ungültiger Wert wird
    abgelehnt); eine fehlende Vorlauf-Konfiguration bleibt für
    map/graph/materialize erlaubt.
    """
    target = review_of or ReviewTarget.IMPLEMENT
    require_valid(issue, Step.REVIEW, target)
    limit = load_feedback_max_chars(Path.cwd())
    feedback = None
    if feedback_file is not None:
        feedback = read_feedback(feedback_file, limit, CONSOLE)
    implement = target is ReviewTarget.IMPLEMENT
    machine = machine_operations(extra, issue) if implement else {}
    halt = run(f"{target.value}.correction", DONE, machine)
    return after_preflight(issue, feedback, flow, halt)

def pass_allowed(flow: PlanningFlow, halt: Halt) -> bool:
    """Ob der Ablauf im erreichten Review PASS zulässt (Wächter)."""
    return allows(flow.flow, halt.state, PASS, halt.context)

def decision_turn(
    issue: BeadInput,
    source: str,
    flow: PlanningFlow,
    run: Run,
    saved: SavedState | None,
) -> tuple[str, int, Halt]:
    """Reviewer-Antwort prüfen und Nachricht laut Tabelle; der Bead
    muss den Umsetzungsvertrag erfüllen (Abnahmekriterien). Die
    Wächter sehen den gespeicherten Laufzustand: nach einem Teillauf
    weist der Ablauf PASS ab. Die Antwort bringt den aktuellen Stand
    mit; hat er sich seit dem Vorlauf geändert, führt PASS zurück in
    den Vorlauf und die nächste Nachricht geht an das Review."""
    require_valid(issue, Step.REVIEW, ReviewTarget.IMPLEMENT)
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
    if saved.state != IMPLEMENT_REVIEW:
        raise DecisionInputError(
            f"Review-Antwort ungültig: der Lauf wartet in "
            f"{saved.state}, nicht in {IMPLEMENT_REVIEW}"
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
            IMPLEMENT_REVIEW,
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
    raw: str, issue: BeadInput, flow: PlanningFlow
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

def changed_since_preflight(flow: PlanningFlow, halt: Halt) -> bool:
    """Die Antwort nahm die Kante zurück in den Vorlauf."""
    entry = halt.entry
    return (
        entry is not None
        and flow.flow.state(entry.target).kind == "machine"
    )

def after_preflight(
    issue: BeadInput,
    feedback: str | None,
    flow: PlanningFlow,
    halt: Halt,
) -> tuple[str, int, Halt]:
    """Nachricht nach der Korrektur oder nach einem neuen Vorlauf:
    die Übergabe des Halts laut Ablauf (Reparatur an den Umsetzer mit
    Exit 1 oder Folgerunde an das Review)."""
    subject = turn_input(issue, flow, halt, feedback=feedback)
    text = hand_over(flow, halt.turn, subject)
    return text, exit_code(subject), halt
