"""Gemeinsame Basis fuer die CLI-Executor-Adapter.

Die Basis kapselt nur den executor-unabhaengigen Teil: den
Prozesslauf und die Weitergabe von ``stdin`` und Timeout. Die
vollstaendige Argumentbildung liegt in der jeweiligen Unterklasse.
"""

from __future__ import annotations

import math
import os
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable

from .contract import (
    ContextMeasurement,
    ContextStatus,
    Measure,
    QuotaMeasurement,
    QuotaStatus,
    TurnRequest,
    TurnResult,
    TurnStatus,
)
from .process import DEFAULT_TIMEOUT_S, run_cli_turn

ProcessRunner = Callable[..., TurnResult]

# Kurze eigene Frist fuer die ``--version``-Probe (R5, ki-dev-ablauf-
# wu0.3): eine lokale Versionsausgabe braucht keine Modell-/
# Netzwerklaufzeit wie ein Turn. Ohne eigene Frist wuerde eine
# haengende Probe mit dem vollen Rollen-Timeout rechnen und den
# nachfolgenden Turn zusaetzlich zu dessen eigener Frist verzoegern
# (docs/cli-adapters.md: "der kleinere Wert aus Rollen-Timeout und
# Budget gilt" -- EIN gemeinsamer Prozesstimeout, keine Verdopplung).
VERSION_PROBE_TIMEOUT_S = 10.0

# Form einer Versionsangabe, die in einer Meldung erscheinen darf;
# andere Probenausgaben bleiben ungenannt.
_SHOWN_VERSION = re.compile(r"^\d+(\.\d+)+[0-9A-Za-z.+-]{0,24}$")


class CliAdapter(ABC):
    """Uebersetzt den Turn-Vertrag in genau einen CLI-Aufruf."""

    name: str = "cli"
    capabilities: frozenset[Measure] = frozenset({Measure.BUDGET})
    # Geprüfte Version (tool-versions.json); nur mit ihr startet ein
    # budgetierter Turn.
    cli_version_pin: str

    def __init__(
        self,
        *,
        executable: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        runner: ProcessRunner = run_cli_turn,
    ) -> None:
        if (
            type(timeout_s) not in (int, float)
            or not math.isfinite(timeout_s)
            or timeout_s <= 0
        ):
            raise ValueError("timeout_s muss positiv und endlich sein")
        self.executable = executable or self.default_executable
        self.timeout_s = timeout_s
        self._runner = runner

    def send_turn(self, request: TurnRequest) -> TurnResult:
        return self._run_process(
            request, self._bound_timeout_s(request)
        )

    def _run_process(
        self, request: TurnRequest, timeout_s: float
    ) -> TurnResult:
        argv = [self.executable, *self.build_argv(request)]
        return self._runner(
            argv,
            stdin=self.message_stdin(request),
            timeout_s=timeout_s,
            cwd=request.workdir,
            env=request.env or None,
        )

    def send_metered_turn(
        self, request: TurnRequest
    ) -> tuple[str | None, TurnResult, bool]:
        """Versionsprobe und Turn eines budgetierten Aufrufs teilen
        sich EINE gemeinsame Zeitgrenze (R5, ki-dev-ablauf-wu0.3):
        die Probe zaehrt vom selben Rollen-Budget statt es zusaetzlich
        zum Turn zu verlaengern. Ist das Budget nach der Probe bereits
        aufgebraucht, startet kein Turn mehr.

        Das dritte Rueckgabefeld ist explizit, ob ein Turn-Prozess
        ueberhaupt gestartet wurde: der Aufrufer darf das TurnResult
        eines nicht gestarteten Turns nicht an ``claude_result()``/
        ``codex_result()`` weiterreichen -- deren Erfolgs-/
        Fehlerauswertung ist fuer ein tatsaechliches Prozessergebnis
        gebaut und wuerde ``TurnStatus.TIMEOUT`` sonst stillschweigend
        auf ``NONZERO_EXIT`` abbilden (siehe ``TurnStatus``-Docstring:
        die vier Status sind bewusst disjunkt)."""
        total = self._bound_timeout_s(request)
        start = time.monotonic()
        cli_version = self.probe_executed_version(
            request, min(VERSION_PROBE_TIMEOUT_S, total)
        )
        if cli_version != self.cli_version_pin:
            refused = self._unverified_version(cli_version)
            return cli_version, refused, False
        remaining = total - (time.monotonic() - start)
        if remaining <= 0:
            result = self._deadline_exhausted_by_probe(total)
            return cli_version, result, False
        return cli_version, self._run_process(request, remaining), True

    def _unverified_version(
        self, cli_version: str | None
    ) -> TurnResult:
        """Ablehnung vor dem Turn: Verbrauch einer nicht geprüften
        Version wäre nur ein ``PARTIAL``-Beleg, der jede weitere
        Reservierung des Laufs sperrt (Sicherheitsvertrag: ein
        unverifizierter Anbieterstand sperrt reale Ausführung). So
        entsteht kein Verbrauch, und nach Installation der geprüften
        Version setzt ``resume`` den Lauf fort."""
        program = os.path.basename(self.executable)
        shown = (
            cli_version
            if cli_version and _SHOWN_VERSION.match(cli_version)
            else "unbekannt"
        )
        return TurnResult(
            status=TurnStatus.START_ERROR,
            exit_code=None,
            stdout="",
            stderr="",
            argv=(),
            duration_s=0.0,
            error=(
                f"{program} {shown} ist nicht geprüft, erwartet "
                f"{self.cli_version_pin} (tool-versions.json); "
                "Aufruf nicht gestartet"
            ),
        )

    def _deadline_exhausted_by_probe(self, total: float) -> TurnResult:
        return TurnResult(
            status=TurnStatus.TIMEOUT,
            exit_code=None,
            stdout="",
            stderr="",
            argv=(),
            duration_s=total,
            error=(
                f"Versionsprobe hat die gemeinsame Zeitgrenze von "
                f"{total:g}s verbraucht; kein Turn gestartet"
            ),
        )

    def _bound_timeout_s(self, request: TurnRequest) -> float:
        return (
            min(self.timeout_s, request.budget.timeout_s)
            if request.budget
            else self.timeout_s
        )

    @property
    @abstractmethod
    def default_executable(self) -> str:
        """Name der lokal installierten, bereits angemeldeten CLI."""

    @abstractmethod
    def build_argv(self, request: TurnRequest) -> list[str]:
        """Executor-spezifische Argumente ohne das Programm selbst."""

    def message_stdin(self, request: TurnRequest) -> str:
        return request.message

    def probe_executed_version(
        self, request: TurnRequest, timeout_s: float
    ) -> str | None:
        """Tatsaechlich ausgefuehrte CLI-Version per ``--version``
        nachweisen (R2, ki-dev-ablauf-wu0.3): ``cli_version_pin``
        ist nur ein gepinnter Bezugsstand, kein Laufzeitnachweis.

        Laeuft mit demselben ``cwd``/``env`` wie der nachfolgende Turn
        (``send_turn``): sonst koennte ein blosser Programmname
        (``self.executable``) ueber ``PATH`` je nach Umgebung auf ein
        anderes Programm aufloesen als das tatsaechlich ausgefuehrte,
        und die Probe waere kein Nachweis fuer diesen Turn.
        ``timeout_s`` ist eine eigene, vom Aufrufer begrenzte Frist
        (siehe ``send_metered_turn``), kein Rollen-Budget.

        Ein fehlgeschlagener oder nicht auswertbarer Probe-Aufruf
        liefert ``None`` statt eines Rueckfalls auf den Pin; wie jede
        andere Version als der Pin startet dann kein Turn
        (``send_metered_turn``).
        """
        probe = self._runner(
            [self.executable, "--version"],
            stdin="",
            timeout_s=timeout_s,
            cwd=request.workdir,
            env=request.env or None,
        )
        if probe.status is not TurnStatus.OK:
            return None
        return self.parse_version(probe.stdout)

    def parse_version(self, raw: str) -> str | None:
        """Extrahiert die Versionsziffer aus ``--version``; je
        Adapter ueberschrieben (providerspezifisches Ausgabeformat)."""
        text = raw.strip()
        return text or None

    def measure_context(self, session_id: str) -> ContextMeasurement:
        """Sitzungsbezogener Kontextmesswert; ``UNSUPPORTED`` als
        sicherer Standard fuer Adapter ohne eigene Messung."""
        del session_id
        return ContextMeasurement(ContextStatus.UNSUPPORTED)

    def measure_quota(self, session_id: str) -> QuotaMeasurement:
        """Fuenfstundenkontingent-Messwert; ``UNSUPPORTED`` als
        sicherer Standard fuer Adapter ohne eigenen Nachweis. Anders
        als bei ``measure_context`` blockiert dieser Standard jeden
        weiteren Aufruf (siehe ``QuotaStatus``), statt ihn
        freizugeben."""
        del session_id
        return QuotaMeasurement(QuotaStatus.UNSUPPORTED)
