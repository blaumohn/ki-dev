"""``ki-dev step``: ein Turn eines Paketablaufs mit dem Executor manual.

step fährt den gewählten Ablauf auf dem einen Ausführer
(:class:`~ki_dev.runner.package.PackageRunner`) bis zur nächsten
Übergabe. Jede Übergabe bearbeitet der Bote (:class:`Messenger`): mit
einer Antwort dieses Aufrufs (``done`` nach dem Schreiben, das Urteil
aus ``--decision-file``) geht der Lauf weiter, sonst gibt step die
Übergabe aus und der Lauf hält in ``awaiting_input``. Den Vorlauf
(``checks``) führt der Ausführer als gebundene Katalogoperation aus.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import NamedTuple, cast

from ki_dev.adapter.contract import AnswerPending, TurnPrompt
from ki_dev.adapter.registry import executor_specs
from ki_dev.flow.binding import OperationSpec
from ki_dev.flow.model import PASS, FlowError, Transition, Turn
from ki_dev.flow.review_flow import ReviewFlow
from ki_dev.ops.checks import PREFLIGHT
from ki_dev.ops.checks.options import (
    CONTROL_SCHEMA,
    check_control,
    control_from,
)
from ki_dev.ops.checks.preflight import report_data, report_of
from ki_dev.ops.checks.run import run_checks
from ki_dev.ops.checks.stand import current_stand
from ki_dev.ops.context.bead_input import BeadInput, criteria_with_refs
from ki_dev.ops.context.beads_reader import read_issue
from ki_dev.ops.context.blocks import TurnInput, state_turn
from ki_dev.ops.context.guidelines import GuidelineSection
from ki_dev.ops.context.limit_config import load_base_max_chars
from ki_dev.review_decision import ReviewVerdict
from ki_dev.runner.bound import BoundOperations
from ki_dev.runner.dispatch import Dispatch, role_of
from ki_dev.runner.package import Handoff, PackageRunner
from ki_dev.runner.review_model import (
    CHECKED,
    CURRENT,
    FACTS,
    FULL_CHECKS,
    ReviewModel,
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
from ki_dev.step.state import SavedState, run_store
from ki_dev.step.turn import ensure_base_fits, hand_over, require_valid

REVIEW_KIND = "review"
CORRECTION_KIND = "correction"
MACHINE_KIND = "machine"
WRITE_KINDS = ("write", CORRECTION_KIND)

DONE = "done"
"""Ereignis „Schreiben bzw. Korrektur getan“ des Review-Musters:
``--step review`` beginnt mit ihm am Start des Ablaufs."""

# Laufdaten, die step neben denen des Review-Katalogs führt.
ANSWER_FILE = "answer_file"
REPORT = "report"
FINDING = "finding"
VERDICT = "verdict"
CONTROL = "control"


class Output(NamedTuple):
    """Ausgabe eines Bead-Aufrufs: Text, Exitcode, Halt des Laufs und
    der Zustand, in dem dieser Aufruf begann."""

    text: str
    exit_code: int
    state: str
    attempt: str | None
    flow: ReviewFlow
    start: str


@dataclass
class Messenger:
    """Der Mensch als Bote (Executor manual): beantwortet die erste
    Übergabe mit der Antwort dieses Aufrufs, jede weitere gibt step
    aus (der Lauf hält)."""

    answer: str | None = None
    handed: TurnPrompt | None = None
    spec: object = field(
        default_factory=lambda: executor_specs()["manual"]
    )

    def ask(self, request: TurnPrompt) -> str:
        if self.answer is not None:
            answer, self.answer = self.answer, None
            return answer
        self.handed = request
        raise AnswerPending(f"Übergabe {request.key} ausgegeben")


@dataclass
class Rendering:
    """Übergaben dieses Aufrufs aus ihrer Deklaration; ``subject``
    ist die Eingabe der zuletzt gerenderten."""

    issue: BeadInput
    flow: ReviewFlow
    guidelines: Sequence[GuidelineSection] = ()
    limit: int | None = None
    feedback: str | None = None
    subject: TurnInput | None = None

    def handoff(self, handoff: Handoff) -> str:
        return self.text(
            handoff.state, handoff.attempt, handoff.data, handoff.path
        )

    def text(
        self,
        state: str,
        attempt: str | None,
        data: Mapping[str, object],
        path: Sequence[Transition],
    ) -> str:
        turn = _turn(self.flow, state, path)
        subject = self._subject(state, attempt, data, path)
        self.subject = subject
        return hand_over(self.flow, turn, subject, self.limit)

    def _subject(
        self,
        state: str,
        attempt: str | None,
        data: Mapping[str, object],
        path: Sequence[Transition],
    ) -> TurnInput:
        checked = any(
            self.flow.flow.state(t.source).kind == MACHINE_KIND
            for t in path
        )
        report = data.get(REPORT) if checked else None
        finding = data.get(FINDING) if checked else None
        subject = TurnInput(
            self.issue,
            self.flow.flow,
            state,
            guidelines=self.guidelines,
            report=None if report is None else report_of(report),
            finding=cast(str | None, finding),
            feedback_limit=(
                None if finding is None else feedback_limit()
            ),
            feedback=self.feedback,
            pass_allowed=_pass_allowed(self.flow, data),
            attempt=attempt,
        )
        answered = _answered(self.flow, path)
        if answered is None:
            return subject
        control = cast(Mapping[str, dict], data.get(CONTROL) or {})
        return replace(
            subject,
            state=answered.source,
            events=(answered.event,),
            verdict=ReviewVerdict(**cast(dict, data[VERDICT])),
            preflight_args=control.get("args", {}),
            preflight_skip=control.get("skip", {}),
        )


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
    if step is Step.REVIEW and next_turn:
        issue = read_issue(bead_id, Path.cwd())
        if inputs.decision is not None:
            return decision_turn(
                bead_id, issue, inputs.decision, flow, saved
            )
        return next_turn_handoff(
            bead_id, issue, extra, inputs.feedback, flow
        )
    limit = load_base_max_chars(Path.cwd())
    issue = read_issue(bead_id, Path.cwd())
    start = flow.flow.start
    if step is Step.REVIEW:
        review = flow.state_of(REVIEW_KIND)
        guidelines = selected_guidelines(flow, review=True)
        ensure_base_fits(flow, issue, review, limit)
        rendering = Rendering(issue, flow, guidelines, limit)
        return _drive(
            bead_id, flow, issue, extra, rendering, DONE, start
        )
    ensure_base_fits(flow, issue, start, limit)
    guidelines = selected_guidelines(flow, review=False)
    rendering = Rendering(issue, flow, guidelines, limit)
    return _drive(bead_id, flow, issue, extra, rendering, None, start)


def next_turn_handoff(
    bead_id: str,
    issue: BeadInput,
    extra: PreflightRequest,
    feedback_file: str | None,
    flow: ReviewFlow,
) -> Output:
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
    rendering = Rendering(issue, flow, feedback=feedback)
    return _drive(
        bead_id,
        flow,
        issue,
        extra,
        rendering,
        DONE,
        flow.state_of(CORRECTION_KIND),
    )


def decision_turn(
    bead_id: str,
    issue: BeadInput,
    source: str,
    flow: ReviewFlow,
    saved: SavedState | None,
) -> Output:
    """Reviewer-Antwort prüfen und an die wartende Übergabe geben; der
    Bead muss den Umsetzungsvertrag erfüllen (Abnahmekriterien). Die
    Wächter sehen den gespeicherten Lauf: nach einem Teillauf weist
    der Ablauf PASS ab. Die Antwort bringt den aktuellen Stand mit;
    hat er sich seit dem Vorlauf geändert, führt PASS zurück in den
    Vorlauf und die nächste Nachricht geht an das Review."""
    review = flow.state_of(REVIEW_KIND)
    require_valid(issue, flow, review)
    raw = read_decision(source, CONSOLE)
    answer = parse_answer(raw, issue, flow)
    # Die Antwort gilt nur dort, wo der Lauf auf sie wartet: ohne
    # Vorlauf gibt es keine Review-Übergabe, nach einem roten Vorlauf
    # (P.correction) ist ein PASS kein Ausweg.
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
    if answer.attempt != saved.attempt:
        raise DecisionInputError(
            "Review-Antwort ungültig: attempt gehört nicht zum "
            f"wartenden Versuch (wartend: Versuch {saved.attempt})"
        )
    answer_file = None if source == "-" else str(Path(source).resolve())
    exclude = None if answer_file is None else Path(answer_file)
    current = current_stand(Path.cwd(), issue, exclude=exclude)
    if current is None and answer.verdict.event == PASS:
        raise DecisionInputError(
            "Review-Antwort ungültig: PASS braucht einen geprüften "
            "Stand, und den gibt es nur in einem Git-Arbeitsverzeichnis"
        )
    update = {
        VERDICT: {
            "event": answer.verdict.event,
            "detail": answer.verdict.detail,
            "requirement_ref": answer.verdict.requirement_ref,
        },
        CONTROL: dict(
            zip(
                ("args", "skip"),
                control_from(answer.extras),
                strict=True,
            )
        ),
        CURRENT: current,
        ANSWER_FILE: answer_file,
    }
    runner = _runner(
        bead_id,
        flow,
        issue,
        NO_PREFLIGHT_OPTIONS,
        Rendering(issue, flow),
    )
    if not runner.allows(answer.verdict.event, update):
        raise DecisionInputError(
            f"Review-Antwort ungültig: Ereignis {answer.verdict.event} "
            f"in {review} nicht erlaubt (Teillauf: kein PASS)"
        )
    rendering = Rendering(issue, flow)
    return _resume(
        bead_id, flow, issue, rendering, _Answer(raw, update)
    )


@dataclass(frozen=True)
class _Answer:
    """Antwort dieses Aufrufs an die wartende Übergabe: ihr Text und
    die Laufdaten, die sie mitbringt."""

    raw: str
    update: Mapping[str, object] = field(default_factory=dict)


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


def _drive(
    bead_id: str,
    flow: ReviewFlow,
    issue: BeadInput,
    extra: PreflightRequest,
    rendering: Rendering,
    answer: str | None,
    start: str,
) -> Output:
    """Neuer Lauf in ``start``; ``answer`` beantwortet die erste
    Übergabe (``done``), dann bis zur nächsten Übergabe."""
    messenger = Messenger(answer)
    runner = _runner(bead_id, flow, issue, extra, rendering, messenger)
    data = {ANSWER_FILE: _answer_file(bead_id)}
    result = runner.start(data, start, again=True)
    return _output(flow, rendering, messenger, result)


def _answer_file(bead_id: str) -> str | None:
    """Antwortdatei des vorigen Laufs: sie ist Eingabe an ki-dev, auch
    ein späterer Vorlauf zählt sie nicht zum geprüften Stand."""
    record = run_store(bead_id).load_record()
    data = record.get("data") if isinstance(record, Mapping) else None
    value = data.get(ANSWER_FILE) if isinstance(data, Mapping) else None
    return value if isinstance(value, str) else None


def _resume(
    bead_id: str,
    flow: ReviewFlow,
    issue: BeadInput,
    rendering: Rendering,
    answer: _Answer,
) -> Output:
    messenger = Messenger(answer.raw)
    runner = _runner(
        bead_id,
        flow,
        issue,
        NO_PREFLIGHT_OPTIONS,
        rendering,
        messenger,
        answer.update,
    )
    result = runner.resume()
    if any(
        flow.flow.state(t.target).kind == MACHINE_KIND
        and flow.flow.state(t.source).kind == REVIEW_KIND
        for t in result["path"]
    ):
        progress(
            "Stand seit dem Vorlauf geändert (Arbeitsbaum oder Bead): "
            "PASS nicht angenommen, neuer Vorlauf"
        )
    return _output(flow, rendering, messenger, result)


def _output(
    flow: ReviewFlow,
    rendering: Rendering,
    messenger: Messenger,
    result: Mapping[str, object],
) -> Output:
    """Die ausgegebene Übergabe; endet der Lauf ohne Übergabe, die
    Nachricht der letzten Kante (z. B. nach PASS)."""
    path = cast(list[Transition], result["path"])
    state = str(result["state"])
    if messenger.handed is not None:
        text = messenger.handed.prompt
    else:
        text = rendering.text(
            state, None, cast(Mapping, result["data"]), path
        )
    subject = rendering.subject
    code = 0 if subject is None or subject.finding is None else 1
    attempt = cast(str | None, result["attempt"])
    start = path[0].source if path else state
    return Output(text, code, state, attempt, flow, start)


def _runner(
    bead_id: str,
    flow: ReviewFlow,
    issue: BeadInput,
    extra: PreflightRequest,
    rendering: Rendering,
    messenger: Messenger | None = None,
    update: Mapping[str, object] | None = None,
) -> PackageRunner:
    """Der Ausführer für diesen Bead: Vorlauf als Katalogoperation,
    jede Rolle über den Boten."""
    catalog = {
        PREFLIGHT: OperationSpec(
            partial(_checks, issue, extra),
            {"type": "array"},
            {"type": "object"},
        )
    }
    used = {b.do for b in flow.flow.bindings.values()}
    roles = {
        role_of(flow.flow, state.id)
        for state in flow.flow.states.values()
    }
    messenger = messenger or Messenger()

    def render(handoff: Handoff) -> str:
        # Eine Vorab-Antwort braucht keinen Text: die Übergabe, auf
        # die sie antwortet, gab ein früherer Aufruf aus.
        if messenger.answer is not None:
            return ""
        return rendering.handoff(handoff)

    turns = Dispatch(
        flow.flow,
        dict.fromkeys(roles, messenger),
        render=render,
        read=partial(_read, flow, update or {}),
        workdir=Path.cwd(),
    )
    return PackageRunner(
        flow.flow,
        BoundOperations(
            flow.flow.bindings,
            {k: v for k, v in catalog.items() if k in used},
        ),
        run_store(bead_id),
        model=ReviewModel,
        turns=turns,
    )


def _checks(
    issue: BeadInput,
    extra: PreflightRequest,
    answer_file: str | None,
) -> dict[str, object]:
    """Vorlauf dieses Projekts; danach gilt der Stand (Arbeitsbaum,
    Bead), auf dem er lief. Eine Antwortdatei zählt nicht dazu."""
    outcome = run_checks(Path.cwd(), extra.extra, extra.skip, progress)
    partial_run = outcome.report is not None and outcome.report.partial
    exclude = None if answer_file is None else Path(answer_file)
    return {
        "event": outcome.event,
        FACTS: [] if partial_run else [FULL_CHECKS],
        CHECKED: current_stand(Path.cwd(), issue, exclude=exclude),
        REPORT: (
            None
            if outcome.report is None
            else report_data(outcome.report)
        ),
        FINDING: outcome.failure,
    }


def _read(
    flow: ReviewFlow,
    update: Mapping[str, object],
    handoff: Handoff,
    raw: str,
) -> tuple[dict, str]:
    """Antwort des Boten: nach Schreiben und Korrektur ``done``, im
    Review das geprüfte Urteil (vorab gegen den Lauf geprüft)."""
    kind = flow.flow.state(handoff.state).kind
    if kind in WRITE_KINDS:
        return {}, raw
    if kind == REVIEW_KIND:
        verdict = cast(Mapping[str, str], update[VERDICT])
        return dict(update), verdict["event"]
    raise FlowError(f"{handoff.state}: keine Antwort über step")


def _turn(
    flow: ReviewFlow, state: str, path: Sequence[Transition]
) -> Turn:
    """Die Übergabe laut Ablauf: die der letzten Kante des Weges, die
    eine bestimmt, sonst die der Operation des Zustands."""
    for transition in reversed(path):
        if transition.turn is not None:
            return transition.turn
    return state_turn(flow.flow, state)


def _answered(
    flow: ReviewFlow, path: Sequence[Transition]
) -> Transition | None:
    """Die Kante, die eine Review-Antwort in diesem Aufruf nahm, wenn
    sie nicht zurück in den Vorlauf führte."""
    if not path:
        return None
    entry = path[0]
    if flow.flow.state(entry.source).kind != REVIEW_KIND:
        return None
    if flow.flow.state(entry.target).kind == MACHINE_KIND:
        return None
    return entry


def _pass_allowed(flow: ReviewFlow, data: Mapping[str, object]) -> bool:
    """Ob das Review PASS zulassen kann (kein Teillauf)."""
    if not flow.binds(PREFLIGHT):
        return True
    model = ReviewModel(None, dict(data))
    return model.full_checks()

