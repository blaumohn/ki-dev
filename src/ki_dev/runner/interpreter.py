"""Generischer Interpreter eines deklarativen Ablaufs.

Der Ausführer kennt keine Topologie. Er bekommt einen geprüften
:class:`~ki_dev.flow.model.Ablauf`, bindet dessen Vokabular an
Implementierungen (:class:`Bindung`) und wählt zu (Zustand, Ereignis)
den ersten Übergang, dessen Wächter gelten. Welche Wirkung eine Aktion
hat, entscheidet die Bindung; welche Kante gilt, allein der Ablauf.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TypeVar

from ki_dev.flow.model import (
    Ablauf,
    AblaufError,
    Operation,
    Uebergang,
)

K = TypeVar("K")
"""Kontext der Wächter (Zustand, Ereignis, Grenzen, …)."""


@dataclass(frozen=True)
class Bindung[K]:
    """Implementierung des Vokabulars eines Ablaufs.

    ``waechter`` und ``aktionen`` müssen genau die im Ablauf
    deklarierten Namen abdecken; ``eskalationen`` und ``operationen``
    nennen die Namen, die der Ausführer versteht."""

    waechter: Mapping[str, Callable[[K], bool]]
    aktionen: Mapping[str, object]
    eskalationen: frozenset[str]
    operationen: frozenset[str]


@dataclass(frozen=True)
class GebundenerAblauf[K]:
    ablauf: Ablauf
    bindung: Bindung[K]

    def waehle(
        self, zustand: str, ereignis: str, kontext: K
    ) -> Uebergang | None:
        """Erster Kandidat, dessen Wächter gelten; sonst ``None``."""
        for uebergang in self.ablauf.kandidaten(zustand, ereignis):
            if self.gilt(uebergang.wenn, kontext):
                return uebergang
        return None

    def operation(self, zustand: str, kontext: K) -> Operation | None:
        """Was beim Betreten von ``zustand`` auszuführen ist (Moore)."""
        for operation in self.ablauf.zustand(zustand).operationen:
            if self.gilt(operation.wenn, kontext):
                return operation
        return None

    def gilt(self, waechter: Iterable[str], kontext: K) -> bool:
        return all(self._eins(name, kontext) for name in waechter)

    def _eins(self, name: str, kontext: K) -> bool:
        negiert = name.startswith("!")
        wert = self.bindung.waechter[name.removeprefix("!")](kontext)
        return not wert if negiert else wert


def binde[K](
    ablauf: Ablauf, bindung: Bindung[K]
) -> GebundenerAblauf[K]:
    """Prüfen, dass Ablauf und Ausführer dasselbe Vokabular sprechen."""
    vokabular = ablauf.vokabular
    for art, deklariert, implementiert in (
        ("Wächter", vokabular.waechter, bindung.waechter),
        ("Aktionen", vokabular.aktionen, bindung.aktionen),
        ("Eskalationen", vokabular.eskalationen, bindung.eskalationen),
        ("Operationen", vokabular.operationen, bindung.operationen),
    ):
        fehlt = sorted(set(deklariert) - set(implementiert))
        fremd = sorted(set(implementiert) - set(deklariert))
        if fehlt or fremd:
            raise AblaufError(
                f"{ablauf.name}.toml: {art} passen nicht zum Ausführer "
                f"(fehlt: {', '.join(fehlt) or '-'}; "
                f"nicht deklariert: {', '.join(fremd) or '-'})"
            )
    return GebundenerAblauf(ablauf, bindung)
