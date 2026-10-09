"""Übergaben: jede Übergabe an eine Sitzung entsteht hier aus ihrer
Deklaration.

Eine Übergabe ist eine Vorlage (``flow/templates/<ABLAUF>/NAME.txt``),
deren Felder aus der Eingabe stammen, gefolgt von den Kontextbausteinen
in der deklarierten Reihenfolge. Welche Vorlage und welche Bausteine
gelten, steht im Ablauf (:class:`~ki_dev.flow.model.Turn`); der
Ausführer kennt weder Zustände noch Phasen noch Befehle. Felder und
Bausteine steckt der Aufrufer ein (:class:`Plug`), wie eine
Maschinenoperation: ``ki-dev run`` und ``ki-dev step`` rendern über
dieselbe Funktion, Claude, Codex und der Mensch als Bote erhalten
denselben Wortlaut.

Das Ergebnis behält die Teile der Bausteine, damit der Aufrufer Teile
von einer Grenze ausnehmen kann (:meth:`Rendered.text`).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from string import Template

from ki_dev.flow.model import Flow, FlowError, Turn
from ki_dev.flow.templates import text


@dataclass(frozen=True)
class Plug[T]:
    """Was der Aufrufer für die Übergaben eines Ablaufs einsteckt.

    ``fields`` füllen die Platzhalter der Vorlagen, ``blocks`` liefern
    die Zeilen der Kontextbausteine; beide erhalten die Eingabe."""

    fields: Mapping[str, Callable[[T], object]]
    blocks: Mapping[str, Callable[[T], Sequence[str]]]


@dataclass(frozen=True)
class Rendered:
    """Gefüllte Vorlage und Zeilen je Kontextbaustein."""

    head: str
    parts: tuple[tuple[str, tuple[str, ...]], ...]

    def text(self, skip: Iterable[str] = ()) -> str:
        """Der Text der Übergabe, ohne die Bausteine in ``skip``."""
        omitted = set(skip)
        lines = [self.head]
        for name, part in self.parts:
            if name not in omitted:
                lines += part
        return "\n".join(lines) + "\n"


def bind_turns[T](
    flow: Flow, plug: Plug[T], turn_operations: Iterable[str]
) -> None:
    """Ablauf und Aufrufer sprechen dieselben Namen.

    Jede Operation aus ``turn_operations`` nennt eine Vorlage; die
    Kontextbausteine des Ablaufs sind genau die eingesteckten; die
    Felder sind genau die Platzhalter der genannten Vorlagen."""
    wanted = set(turn_operations)
    declared = set(flow.vocabulary.context)
    _same(flow, "Kontextbausteine", declared, set(plug.blocks))
    used: set[str] = set()
    for state in flow.states.values():
        for operation in state.operations:
            if operation.do in wanted and operation.template is None:
                raise FlowError(
                    f"{flow.name}.toml: state {state.id}: "
                    f"{operation.do} ohne Vorlage"
                )
    for turn in declared_turns(flow):
        used |= _identifiers(flow, turn)
    _same(flow, "Felder", used, set(plug.fields))


def declared_turns(flow: Flow) -> list[Turn]:
    """Alle Übergaben des Ablaufs: an Operationen und an Kanten."""
    turns = [
        operation.turn
        for state in flow.states.values()
        for operation in state.operations
        if operation.turn is not None
    ]
    turns += [t.turn for t in flow.transitions if t.turn is not None]
    return turns


def render_turn[T](
    flow: Flow, turn: Turn, subject: T, plug: Plug[T]
) -> Rendered:
    """Vorlage füllen, danach die Bausteine in deklarierter
    Reihenfolge."""
    source = Template(text(flow.name, turn.template))
    values = {
        name: plug.fields[name](subject)
        for name in source.get_identifiers()
    }
    return Rendered(
        source.substitute(values),
        tuple(
            (name, tuple(plug.blocks[name](subject)))
            for name in turn.context
        ),
    )


def _identifiers(flow: Flow, turn: Turn) -> set[str]:
    source = Template(text(flow.name, turn.template))
    return set(source.get_identifiers())


def _same(
    flow: Flow, kind: str, declared: set[str], plugged: set[str]
) -> None:
    missing = sorted(declared - plugged)
    foreign = sorted(plugged - declared)
    if missing or foreign:
        raise FlowError(
            f"{flow.name}.toml: {kind} passen nicht zum Aufrufer "
            f"(fehlt: {', '.join(missing) or '-'}; nicht deklariert: "
            f"{', '.join(foreign) or '-'})"
        )
