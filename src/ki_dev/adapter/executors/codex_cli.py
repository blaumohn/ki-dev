"""Codex-CLI-Adapter: neue oder bestehende Sitzung, ein Turn je Aufruf.

Die unterstuetzte CLI-Syntax ist in ``docs/cli-adapters.md``
dokumentiert. Der Adapter nutzt ausschliesslich die lokal
installierte, bereits angemeldete ``codex``-CLI.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from ki_dev.tool_versions import load_tool_versions

from .base import CliAdapter
from .codex_quota import QuotaPending, codex_quota
from .codex_sessions import validate_codex_session_id
from .contract import (
    Access,
    Measure,
    QuotaMeasurement,
    QuotaStatus,
    TurnRequest,
    TurnResult,
)
from .metering import codex_result, missing_result

# Gemeinsamer Versionsstand fuer Build und Laufzeit.
CLI_VERSION = load_tool_versions()["CODEX_VERSION"]

# Beobachtetes Format von ``codex --version``, z. B.
# "codex-cli 0.154.0".
_VERSION_OUTPUT = re.compile(r"^codex-cli\s+(\S+)")
# Dateizugriff als Codex-Sandbox; gilt fuer ``exec`` und ``resume``.
_SANDBOX = {Access.READ: "read-only", Access.WRITE: "workspace-write"}


class CodexCliAdapter(CliAdapter):
    """Ein Turn in einer Codex-CLI-Sitzung: ohne ``session_id`` legt
    ``codex exec`` eine neue an (ID aus ``thread.started``), sonst
    setzt ``codex exec resume`` die genannte fort.

    Ohne native Turn-/Kosten-/Kontextgrenzen (siehe
    ``docs/cli-adapters.md``) bietet Codex keine lokale, vergleichbare
    Kontextmessung wie Claudes Sitzungsprotokoll; ``measure_context``
    bleibt deshalb bewusst beim ``UNSUPPORTED``-Standard aus
    ``CliAdapter`` statt eine ungeprüfte Messquelle zu erfinden.

    ``measure_quota`` dagegen liest den zuletzt bekannten
    5h-Kontingentverbrauch aus der lokalen Rollout-Ablage
    (``codex_quota``, verbrauchsfrei) -- Codex fuehrt diesen
    Nachweis anders als den Kontext, siehe ``docs/cli-adapters.md``.
    """

    name = "codex-cli"
    capabilities = frozenset({Measure.QUOTA, Measure.BUDGET})
    cli_version_pin = CLI_VERSION

    @property
    def default_executable(self) -> str:
        return "codex"

    def measure_quota(self, session_id: str | None) -> QuotaMeasurement:
        try:
            used_percent, resets_at = codex_quota(
                session_id, Path.home() / ".codex/sessions"
            )
        except QuotaPending as exc:
            return QuotaMeasurement(
                QuotaStatus.PENDING, detail=str(exc)
            )
        except (OSError, ValueError) as exc:
            return QuotaMeasurement(
                QuotaStatus.UNAVAILABLE, detail=str(exc)
            )
        return QuotaMeasurement(
            QuotaStatus.MEASURED,
            used_percent=used_percent,
            resets_at=resets_at,
        )

    def parse_version(self, raw: str) -> str | None:
        match = _VERSION_OUTPUT.match(raw.strip())
        return match.group(1) if match else None

    def send_turn(self, request: TurnRequest) -> TurnResult:
        if not request.budget:
            if request.session_id is None:
                # Die ID einer neuen Sitzung nennt nur ``--json``.
                raise ValueError(
                    "neue Codex-Sitzung nur mit TurnBudget (--json)"
                )
            return super().send_turn(request)
        cli_version, result, turn_ran = self.send_metered_turn(request)
        if not turn_ran:
            return result
        session_id = request.session_id
        if session_id is None and result.ok:
            try:
                session_id = _started_thread(result.stdout)
            except ValueError as exc:
                return missing_result(result, str(exc))
        return replace(
            codex_result(
                result,
                session_id=session_id,
                cli_version=cli_version,
            ),
            session_id=session_id,
        )

    def _run_process(
        self, request: TurnRequest, timeout_s: float
    ) -> TurnResult:
        """Codex liest das Antwortschema aus einer Datei; sie gilt nur
        für diesen Aufruf und liegt außerhalb des Worktrees."""
        if request.output_schema is None:
            return super()._run_process(request, timeout_s)
        with TemporaryDirectory(prefix="ki-dev-schema-") as folder:
            schema_file = Path(folder) / "output-schema.json"
            schema_file.write_text(
                json.dumps(request.output_schema), encoding="utf-8"
            )
            argv = [
                self.executable,
                *self.build_argv(request, schema_file),
            ]
            return self._runner(
                argv,
                stdin=self.message_stdin(request),
                timeout_s=timeout_s,
                cwd=request.workdir,
                env=request.env or None,
            )

    def build_argv(
        self, request: TurnRequest, schema_file: Path | None = None
    ) -> list[str]:
        # ``-`` weist ``codex exec`` an, den Prompt von stdin zu
        # lesen. Effort und Sandbox gehen als Codex-
        # Konfigurationsschluessel mit (``-c``, auch bei ``resume``).
        argv = ["exec"]
        if request.session_id is not None:
            argv += ["resume", request.session_id]
        argv += [
            "--model",
            request.model,
            "-c",
            f"model_reasoning_effort={request.effort.value}",
        ]
        if request.access is not None:
            argv += ["-c", f'sandbox_mode="{_SANDBOX[request.access]}"']
        if request.budget:
            argv.append("--json")
        if schema_file is not None:
            argv += ["--output-schema", str(schema_file)]
        argv.append("-")
        return argv


def _started_thread(stdout: str) -> str:
    """ID einer neuen Sitzung aus dem ``thread.started``-Ereignis von
    ``codex exec --json``."""
    events = [json.loads(line) for line in stdout.splitlines()]
    started = [
        event
        for event in events
        if isinstance(event, dict)
        and event.get("type") == "thread.started"
    ]
    if not started:
        raise ValueError(
            "Codex-Sitzungs-ID fehlt (kein thread.started)"
        )
    thread_id = started[0].get("thread_id")
    if not isinstance(thread_id, str):
        raise ValueError("Codex-thread_id ist kein Text")
    validate_codex_session_id(thread_id)
    return thread_id
