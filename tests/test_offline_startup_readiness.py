"""Startfreigabe-Nachweis fuer p0h (ki-dev-ablauf-p0h.6).

Verbindet, ohne einen einzigen Modell-/CLI-Aufruf: den lesenden
Statuspfad (p0h.2), die Auftragsbindung fuer CHANGES (p0h.1), die
Stillstands-Eskalation (p0h.4), die technische Umgebungsbindung
(p0h.3) und die begrenzte Diff-Projektion (p0h.5) -- gegen einen
echten Git-Worktree und die echte ``RepositoryEvidenceCollector``.
Fake-Executoren ersetzen ausschliesslich den externen CLI-Prozess;
Auftragsbindung, Fortschrittsregel, Statuspfad und Projektion laufen
im echten Produktionscode.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from plumbum import CommandNotFound, local

from ki_dev.adapter.agent import (
    AgentBuildMode,
    AgentReviewer,
)
from ki_dev.adapter.contract import (
    RunTask,
)
from ki_dev.adapter.executors.contract import (
    ContextMeasurement,
    ContextStatus,
    Effort,
    QuotaMeasurement,
    QuotaStatus,
    TurnRequest,
    TurnResult,
    TurnStatus,
)
from ki_dev.ausfuehrer.machine import Limits, Phase
from ki_dev.ausfuehrer.run_cli import status_run
from ki_dev.ausfuehrer.run_runtime import RunRuntime
from ki_dev.ausfuehrer.run_safety import SafetyLimits
from ki_dev.repository_evidence import RepositoryEvidenceCollector
from ki_dev.repository_finalization import StaticFinalizer
from ki_dev.run_store import RunStore


def _bd_available() -> bool:
    try:
        local["bd"]
    except CommandNotFound:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _bd_available(), reason="bd lokal nicht installiert"
)


class FakeExecutor:
    """Ersetzt genau den externen CLI-Prozess durch ein Skript.

    ``send_turn`` erhaelt den echten, vollstaendig gebauten
    ``TurnRequest`` (inkl. ``workdir``/``env``) und den echten,
    projizierten Review-Prompt in ``message`` -- beides technisch
    erzeugt vom Produktionscode, nicht vom Test vorgegeben.
    """

    name = "fake-agent"

    def __init__(self, script) -> None:
        self._script = list(script)
        self.requests: list[TurnRequest] = []

    def send_turn(self, request: TurnRequest) -> TurnResult:
        self.requests.append(request)
        stdout = self._script.pop(0)(request)
        return TurnResult(
            TurnStatus.OK,
            0,
            stdout,
            "",
            (),
            0.01,
            usage={
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        )

    def measure_context(self, session_id: str) -> ContextMeasurement:
        del session_id
        return ContextMeasurement(ContextStatus.UNSUPPORTED)

    def measure_quota(self, session_id: str) -> QuotaMeasurement:
        del session_id
        return QuotaMeasurement(
            QuotaStatus.MEASURED,
            used_percent=0.0,
            resets_at=9_999_999_999,
        )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True
    )


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "worktree"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "test")
    _git(repo, "config", "user.email", "test@example.invalid")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "base")
    subprocess.run(
        ["bd", "init", "--quiet", "--non-interactive"],
        check=True,
        capture_output=True,
        cwd=repo,
    )
    return repo


def _task(repo: Path) -> RunTask:
    return RunTask(
        run_id="offline-readiness",
        task="greeting.txt mit korrektem Gruss und Zeilenumbruch "
        "anlegen",
        sources=("docs/vertrag.md",),
        workdir=repo,
        access_profile="write",
        acceptance_criteria=(
            "greeting.txt enthaelt das Wort 'hello' korrekt "
            "geschrieben",
            "greeting.txt endet mit einem Zeilenumbruch",
        ),
        env={"KI_DEV_TEST_MARKER": "bound-worktree"},
    )


def _review_json(run_id: str, round_id: int, action: str, **extra):
    payload = {
        "run_id": run_id,
        "round_id": round_id,
        "action": action,
        "detail": "",
        "requirement_ref": None,
    }
    payload.update(extra)
    return json.dumps(payload)


def test_offline_run_connects_reader_contract_progress_env_projection(
    tmp_path,
):
    repo = _init_repo(tmp_path)
    task = _task(repo)
    run_id = task.run_id

    def write_typo(request: TurnRequest) -> str:
        assert request.workdir == repo  # p0h.3: technische cwd-Bindung
        assert request.env == {"KI_DEV_TEST_MARKER": "bound-worktree"}
        (repo / "greeting.txt").write_text("helo")
        return "greeting.txt angelegt"

    def fix_typo(request: TurnRequest) -> str:
        assert request.workdir == repo
        (repo / "greeting.txt").write_text("hello\n")
        return "Tippfehler behoben, Zeilenumbruch ergaenzt"

    def demand_fix(request: TurnRequest) -> str:
        # p0h.5: der echte, begrenzte Diff erreicht den Reviewer.
        assert "+helo" in request.message
        assert "AC1:" in request.message
        return _review_json(
            run_id,
            1,
            "CHANGES",
            detail="'helo' ist kein korrektes 'hello'",
            requirement_ref="AC1",
        )

    def approve(request: TurnRequest) -> str:
        assert "+hello" in request.message
        return _review_json(run_id, 2, "PASS")

    build = AgentBuildMode(
        FakeExecutor([write_typo, fix_typo]),
        "build-session",
        "model",
        Effort.LOW,
    )
    review = AgentReviewer(
        FakeExecutor([demand_fix, approve]),
        "review-session",
        "model",
        Effort.LOW,
    )
    runs_dir = tmp_path / "runs"
    with RunRuntime(
        RunStore(runs_dir, run_id),
        build,
        review,
        RepositoryEvidenceCollector(),
        StaticFinalizer(),
        safety_limits=SafetyLimits(max_agent_calls=20),
    ) as runtime:
        result = runtime.start(
            task,
            Limits(changes_rounds=3),
            # entspricht dem, was start_from_config() im echten CLI-Pfad
            # persistiert; status_run() setzt das voraus.
            manifest_extra={"configuration": {}},
        )

    assert result.status == "passed"
    assert (repo / "greeting.txt").read_text() == "hello\n"

    # p0h.2: der lesende Statuspfad liest denselben Endzustand, ohne
    # einen eigenen RunRuntime aufzubauen.
    read_only = status_run(run_id, runs_dir=runs_dir)
    assert read_only.status == "passed"
    assert read_only.phase is Phase.PASSED
    assert read_only.round_id == result.round_id


def test_offline_run_pauses_on_stagnation_and_stays_readable(tmp_path):
    repo = _init_repo(tmp_path)
    task = _task(repo)
    run_id = task.run_id

    def touch(request: TurnRequest) -> str:
        (repo / "greeting.txt").write_text(
            f"helo {len(request.message)}"
        )
        return "Versuch"

    def still_wrong(round_id: int):
        def _review(request: TurnRequest) -> str:
            return _review_json(
                run_id,
                round_id,
                "CHANGES",
                detail="weiterhin 'helo' statt 'hello'",
                requirement_ref="AC1",
            )

        return _review

    build = AgentBuildMode(
        FakeExecutor([touch, touch]), "build-session", "m", Effort.LOW
    )
    review = AgentReviewer(
        FakeExecutor([still_wrong(1), still_wrong(2)]),
        "review-session",
        "m",
        Effort.LOW,
    )
    runs_dir = tmp_path / "runs"
    with RunRuntime(
        RunStore(runs_dir, run_id),
        build,
        review,
        RepositoryEvidenceCollector(),
        StaticFinalizer(),
        safety_limits=SafetyLimits(
            max_agent_calls=20,
            max_failed_corrections=10,
            max_stagnant_changes=2,
        ),
    ) as runtime:
        result = runtime.start(
            task,
            Limits(changes_rounds=5),
            manifest_extra={"configuration": {}},
        )

    # p0h.4: zwei CHANGES in Folge an AC1 halten vor der dritten
    # Baurunde an -- unabhaengig davon, dass jede Runde denselben
    # Bau-Fake erneut aufruft.
    assert result.status == "paused_interactive"
    assert "Stillstand" in result.detail
    assert "AC1" in result.detail

    handoffs = list((runs_dir / run_id / "handoff").glob("*.json"))
    assert len(handoffs) == 1
    handoff = json.loads(handoffs[0].read_text())
    assert handoff["open_requirement_ref"] == "AC1"
    assert handoff["acceptance_criteria"] == list(
        task.acceptance_criteria
    )

    # p0h.2: ein frischer, rein lesender Zugriff sieht denselben
    # angehaltenen Zustand, ohne den Lauf fortzusetzen oder zu
    # veraendern.
    before = (repo / "greeting.txt").read_text()
    read_only = status_run(run_id, runs_dir=runs_dir)
    assert read_only.status == "paused_interactive"
    assert read_only.round_id == result.round_id
    assert (repo / "greeting.txt").read_text() == before
