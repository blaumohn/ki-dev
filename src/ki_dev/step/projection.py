"""``ki-dev -f ABLAUF step``: ein Turn eines Paketablaufs mit dem
Executor manual, zustandslos.

Der Aufruf nennt den Zustand und die Antworten (je Zustand eine
Datei). step fährt den Ablauf auf dem einen Ausführer
(:class:`~ki_dev.runner.package.PackageRunner`) ab diesem Zustand, in
einem Lauf, der nur für diesen Aufruf besteht. Jede Übergabe
bearbeitet der Bote (:class:`Messenger`): hat der Zustand eine
Antwort, deuten die Ops des Pakets sie und der Ablauf nimmt die Kante,
sonst gibt step die Übergabe aus. Antworten früherer Zustände liefern
Laufdaten von weiter vorn; was eine Übergabe oder Kante davon braucht,
deklariert der Ablauf (``input``), fehlt etwas, nennt step Name und
Herkunft. Nichts wird gespeichert, nichts erraten.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import NamedTuple, cast

from ki_dev.adapter.contract import AnswerPending, TurnPrompt
from ki_dev.adapter.registry import executor_specs
from ki_dev.flow.binding import BindingError
from ki_dev.flow.model import Flow, Operation, Transition, Turn
from ki_dev.fsm import TransitionNotAllowed
from ki_dev.ops.context.bead_input import BeadInput
from ki_dev.ops.context.beads_reader import read_issue
from ki_dev.ops.context.blocks import MissingTurnData, TurnInput
from ki_dev.ops.context.guidelines import GuidelineSection
from ki_dev.ops.context.limit_config import load_base_max_chars
from ki_dev.run_store import RunStore
from ki_dev.runner.bound import BoundOperations
from ki_dev.runner.dispatch import Dispatch, role_of
from ki_dev.runner.package import Handoff, PackageRunner
from ki_dev.step.options import NO_PREFLIGHT_OPTIONS, PreflightRequest
from ki_dev.step.package import AnswerError, Call, PackageOps
from ki_dev.step.turn import hand_over, require_valid

Guidelines = Callable[[str], Sequence[GuidelineSection]]
"""Leitlinien der Übergabe in einem Zustand."""


class InputMissingError(ValueError):
    """Eine Übergabe oder Kante braucht Laufdaten, die dieser Aufruf
    nicht mitbringt (Exit 2)."""

    def __init__(self, where: str, name: str, origin: str | None):
        source = (
            f"aus {origin}; Antwort mitgeben: {origin}=DATEI.json"
            if origin is not None
            else "Herkunft im Ablauf nicht deklariert"
        )
        super().__init__(f"{where} braucht {name} ({source})")


class Output(NamedTuple):
    """Ausgabe eines Aufrufs: Text, Exitcode und der Zustand, in dem
    der Lauf hält oder endet."""

    text: str
    exit_code: int
    state: str


@dataclass
class Messenger:
    """Der Mensch als Bote (Executor manual): beantwortet die erste
    Übergabe mit der Antwort dieses Aufrufs, die nächste gibt step
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
    flow: Flow
    ops: PackageOps
    guidelines: Guidelines
    limit: int | None = None
    subject: TurnInput | None = None

    def text(
        self,
        state: str,
        data: Mapping[str, object],
        path: Sequence[Transition],
    ) -> str | None:
        """Übergabe in ``state`` nach dem Weg ``path``; ``None``, wenn
        der Ablauf dort keine bestimmt (Ende ohne Nachricht)."""
        declared = _declared_turn(self.flow, state, path)
        if declared is None:
            return None
        turn, inputs = declared
        missing_input(f"Übergabe in {state}", inputs, data)
        if handoff_operation(self.flow, state) is not None:
            require_valid(self.issue, self.flow, state)
        base = TurnInput(
            self.issue,
            self.flow,
            state,
            guidelines=(
                self.guidelines(state)
                if "guidelines" in turn.context
                else ()
            ),
        )
        self.subject = self.ops.subject(base, data, path)
        try:
            return hand_over(self.flow, turn, self.subject, self.limit)
        except MissingTurnData as exc:
            raise InputMissingError(
                f"Übergabe in {state}", exc.name, None
            ) from exc


def handoff_operation(flow: Flow, state: str) -> Operation | None:
    """Die Übergabe an einen Executor in ``state`` (``turn``/``ask``:
    Operation mit Vorlage und ohne Bindung) oder ``None``."""
    for operation in flow.state(state).operations:
        if (
            operation.turn is not None
            and operation.do not in flow.bindings
        ):
            return operation
    return None


def missing_input(
    where: str,
    inputs: Sequence[tuple[str, str]],
    data: Mapping[str, object],
) -> None:
    """Deklarierte Eingaben müssen in den Laufdaten stehen."""
    for name, origin in inputs:
        if name not in data:
            raise InputMissingError(where, name, origin)


@dataclass(frozen=True)
class Request:
    """Was der Aufruf nennt: Bead, Zustand, die Antworten je Zustand
    in Aufrufreihenfolge und die Optionen des Vorlaufs."""

    bead_id: str
    position: str
    answers: Sequence[tuple[str, str]] = ()
    preflight: PreflightRequest = NO_PREFLIGHT_OPTIONS

    @property
    def answer(self) -> str | None:
        """Die Antwort auf die Übergabe in ``position``, falls
        mitgegeben."""
        return next(
            (raw for s, raw in self.answers if s == self.position), None
        )

    @property
    def earlier(self) -> list[tuple[str, str]]:
        """Antworten früherer Zustände: Laufdaten von weiter vorn."""
        return [
            (s, raw) for s, raw in self.answers if s != self.position
        ]


def step_output(
    request: Request,
    flow: Flow,
    ops: PackageOps,
    guidelines: Guidelines,
) -> Output:
    """Übergabe in ``request.position`` (ohne Antwort dort) oder die
    nächste nach ihrer Antwort. Die Basisgrenze wird vor jedem
    Beads-Zugriff gelesen."""
    limit = load_base_max_chars(Path.cwd())
    issue = read_issue(request.bead_id, Path.cwd())
    require_valid(issue, flow, request.position)
    package = Package.create(flow, ops, Call(issue, request.preflight))
    rendering = Rendering(issue, flow, ops, guidelines, limit)
    messenger = Messenger(request.answer)
    result = package.run(request, rendering, messenger)
    return _output(rendering, messenger, result)


@dataclass
class Package:
    """Ablauf und Ops des Pakets für diesen Aufruf, mit den
    eingesteckten Katalogoperationen; ``answered`` ist das Ereignis,
    das die Antwort dieses Aufrufs brachte (Zustand, Ereignis)."""

    flow: Flow
    ops: PackageOps
    call: Call
    bound: BoundOperations
    answered: tuple[str, str] | None = None

    @classmethod
    def create(cls, flow: Flow, ops: PackageOps, call: Call) -> Package:
        used = {b.do for b in flow.bindings.values()}
        catalog = ops.catalog(call)
        bound = BoundOperations(
            flow.bindings,
            {k: v for k, v in catalog.items() if k in used},
        )
        return cls(flow, ops, call, bound)

    def run(
        self,
        request: Request,
        rendering: Rendering,
        messenger: Messenger,
    ) -> Mapping[str, object]:
        """Ein Lauf nur für diesen Aufruf, ab ``request.position`` mit
        den Laufdaten aus früheren Antworten."""
        data: dict[str, object] = {}
        for state, raw in request.earlier:
            data.update(self.earlier(state, raw, data))
        with TemporaryDirectory(prefix="ki-dev-step-") as root:
            runner = PackageRunner(
                self.flow,
                self.bound,
                RunStore(Path(root), request.bead_id),
                model=self.ops.model,
                turns=self.dispatch(rendering, messenger),
                flow_limits=self.ops.flow_limits,
                flow_limits_schema=self.ops.flow_limits_schema,
            )
            try:
                return runner.start(data, request.position)
            except TransitionNotAllowed as exc:
                # Ohne Antwort dieses Aufrufs ist es ein Programmfehler.
                if self.answered is None:
                    raise
                raise self._refused(*self.answered) from exc

    def _refused(self, state: str, event: str) -> AnswerError:
        """Die Kantenwahl der Bibliothek wies das Ereignis der Antwort
        ab: kein Wächter seiner Kanten gilt."""
        candidates = self.flow.candidates(state, event)
        guards = sorted({n for t in candidates for n in t.cond})
        return AnswerError(
            f"Antwort in {state}: Ereignis {event} nicht erlaubt "
            f"(Wächter {', '.join(guards)})"
        )

    def earlier(
        self, state: str, raw: str, data: Mapping[str, object]
    ) -> dict:
        """Laufdaten aus der Antwort eines früheren Zustands, gedeutet
        wie beim Ausführer: eine Übergabe von den Ops, eine
        Katalogoperation über ihre Bindung (ihr Ergebnis). Nachgeprüft
        wird nichts; der Mensch verantwortet die Datei."""
        operation = next(
            (
                op.do
                for op in self.flow.state(state).operations
                if op.do in self.bound.bindings
            ),
            None,
        )
        if operation is None:
            handoff = Handoff(state, "", dict(data))
            return self.ops.read(self.call, handoff, raw)[0]
        try:
            return self.bound.accept(operation, json.loads(raw))[0]
        except (json.JSONDecodeError, BindingError) as exc:
            raise AnswerError(
                f"Antwort von {state} ungültig: {exc}"
            ) from exc

    def dispatch(
        self, rendering: Rendering, messenger: Messenger
    ) -> Dispatch:
        """Jede Rolle über den Boten; die Ops deuten die Antwort, der
        Ablauf muss die Kante ihres Ereignisses nehmen können."""

        def render(handoff: Handoff) -> str:
            # Eine Vorab-Antwort braucht keinen Text: die Übergabe,
            # auf die sie antwortet, gab ein früherer Aufruf aus.
            if messenger.answer is not None:
                return ""
            path = handoff.path
            text = rendering.text(handoff.state, handoff.data, path)
            return text or ""

        def read(handoff: Handoff, raw: str) -> tuple[dict, str]:
            update, event = self.ops.read(self.call, handoff, raw)
            self.check_edge(
                handoff.state, event, {**handoff.data, **update}
            )
            return update, event

        roles = {role_of(self.flow, s) for s in self.flow.states}
        return Dispatch(
            self.flow,
            dict.fromkeys(roles, messenger),
            render=render,
            read=read,
            workdir=Path.cwd(),
        )

    def check_edge(
        self, state: str, event: str, data: Mapping[str, object]
    ) -> None:
        """Das Ereignis der Antwort hat in ``state`` eine Kante, und
        deren Eingaben liegen vor; ob ein Wächter sie zulässt, prüft die
        Kantenwahl der Bibliothek (:meth:`_refused`)."""
        candidates = self.flow.candidates(state, event)
        if not candidates:
            raise AnswerError(
                f"Antwort in {state}: Ereignis {event} hat keine Kante"
            )
        for transition in candidates:
            missing_input(
                f"{state} --{event}-->", transition.inputs, data
            )
        self.answered = (state, event)


def _output(
    rendering: Rendering,
    messenger: Messenger,
    result: Mapping[str, object],
) -> Output:
    """Die ausgegebene Übergabe; endet der Lauf ohne Übergabe, die
    Nachricht der letzten Kante (z. B. nach PASS). Exit 1, wenn die
    Übergabe einen Befund trägt."""
    state = str(result["state"])
    path = cast(list[Transition], result["path"])
    if messenger.handed is not None:
        text = messenger.handed.prompt
    else:
        # Endzustand ist das Ziel der letzten Kante: nach dem Ende
        # zeigt die Konfiguration der Lauf-Maschine in der Region
        # ``ablauf`` wieder deren Anfangszustand (beobachtet, getestet
        # in tests/test_step_package.py, Ende des Ablaufs).
        state = path[-1].target if path else state
        data = cast(Mapping[str, object], result["data"])
        text = rendering.text(state, data, path) or (
            f"Ende: {state} (keine weitere Übergabe)\n"
        )
    subject = rendering.subject
    code = 0 if subject is None or subject.finding is None else 1
    return Output(text, code, state)


def _declared_turn(
    flow: Flow, state: str, path: Sequence[Transition]
) -> tuple[Turn, Sequence[tuple[str, str]]] | None:
    """Die Übergabe laut Ablauf mit ihren Eingaben: die der letzten
    Kante des Weges, die eine bestimmt, sonst die der Operation des
    Zustands."""
    for transition in reversed(path):
        if transition.turn is not None:
            return transition.turn, transition.inputs
    operation = handoff_operation(flow, state)
    if operation is None or operation.turn is None:
        return None
    return operation.turn, operation.inputs
