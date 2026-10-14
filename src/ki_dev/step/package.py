"""Schnittstelle step ↔ Paket: was ein Ablauf für
``ki-dev -f ABLAUF step`` liefert.

step ist zustandslos: der Aufruf nennt den Zustand und die Antworten.
step fährt den Ablauf ab diesem Zustand, führt jede Rolle über den
Boten (Executor manual) aus und gibt die nächste Übergabe aus. Was eine
Antwort bedeutet, welche Katalogoperationen der Ablauf eingesteckt
bekommt und welche Eingaben eine Übergabe außer Bead und Leitlinien
braucht, liefern die Ops des Pakets: das Modul ``ops`` des Ablaufs mit
``package_ops(flow)`` (bei Mustern aus dem Katalog).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from ki_dev.flow.binding import OperationSpec
from ki_dev.flow.model import Flow, FlowError, Transition
from ki_dev.flow.package import import_ops
from ki_dev.ops.context.bead_input import BeadInput
from ki_dev.ops.context.blocks import TurnInput
from ki_dev.runner.package import Handoff
from ki_dev.runner.protocol import RunModel
from ki_dev.step.options import NO_PREFLIGHT_OPTIONS, PreflightRequest


class AnswerError(ValueError):
    """Eine Antwort verletzt den Vertrag ihres Zustands (Exit 2),
    ohne Rohwerte."""


@dataclass(frozen=True)
class Call:
    """Eingaben dieses Aufrufs an das Paket: Bead und die Optionen
    des Vorlaufs."""

    issue: BeadInput
    preflight: PreflightRequest = NO_PREFLIGHT_OPTIONS


class PackageOps(Protocol):
    """Ops eines Pakets für step."""

    model: type[RunModel]
    """Wächter und Aktionen des Ablaufs."""

    def catalog(self, call: Call) -> Mapping[str, OperationSpec]:
        """Katalogoperationen, die der Ablauf binden kann."""
        ...

    def read(
        self, call: Call, handoff: Handoff, raw: str
    ) -> tuple[dict, str]:
        """Antwort auf die Übergabe in ``handoff.state`` prüfen und
        deuten: neue Laufdaten und Ereignis; ein Vertragsfehler ist
        :class:`AnswerError`."""
        ...

    def subject(
        self,
        base: TurnInput,
        data: Mapping[str, object],
        path: Sequence[Transition],
    ) -> TurnInput:
        """Eingaben der Übergabe aus den Laufdaten und dem Weg dieses
        Aufrufs ergänzen."""
        ...

    def review(self, state: str) -> bool:
        """Ob die Übergabe in ``state`` prüft (Leitlinien mit ihrem
        Review-Teil)."""
        ...


def load_package_ops(flow: Flow) -> PackageOps:
    """Ops des Pakets für step; ein Ablauf ohne sie läuft nicht über
    step."""
    if flow.ops is None:
        raise FlowError(f"{flow.name}.toml: kein ops-Modul für step")
    module = import_ops(flow)
    factory = getattr(module, "package_ops", None)
    if not callable(factory):
        raise FlowError(
            f"{flow.name}.toml: ops-Modul {flow.ops} ohne "
            "package_ops(flow)"
        )
    return factory(flow)
