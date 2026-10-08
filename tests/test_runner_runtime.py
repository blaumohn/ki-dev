from __future__ import annotations

import json
from pathlib import Path

import pytest

from ki_dev.adapter.contract import (
    RunTask,
    WorkReport,
)
from ki_dev.adapter.manual import ManualRelay
from ki_dev.deltas import (
    BeadsDelta,
    ChangeMedium,
    CombinedDelta,
    ControllerContext,
    DeltaScope,
    GitDelta,
    GitFileChange,
    RefBoundary,
    RoundStatus,
    VcsRef,
)
from ki_dev.repository_finalization import StaticFinalizer
from ki_dev.review_decision import (
    ReviewAction,
)
from ki_dev.run_store import RunStore
from ki_dev.runner import runtime
from ki_dev.runner.machine import Limits, Phase
from ki_dev.runner.review_output import AgentProtocolError
from ki_dev.runner.runtime import (
    RunResumeError,
    RunRuntime,
    StaticEvidenceCollector,
)


class FakeWorker:
    def __init__(self, *, crash: bool = False) -> None:
        self.calls = 0
        self.crash = crash

    def work(self, request):
        self.calls += 1
        if self.crash:
            raise SystemExit("simulierter Prozessabbruch")
        return WorkReport(f"Bau {request.round_id}")


class FailingBuilder(FakeWorker):
    def work(self, request):
        del request
        self.calls += 1
        raise RuntimeError("Prozessfehler")


class FakeReviewer:
    def __init__(self, actions) -> None:
        self.actions = list(actions)
        self.calls = 0

    def review(self, request):
        item = self.actions[self.calls]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        if type(item) is str:
            return item
        action, ref = (
            item if isinstance(item, tuple) else (item, "AC1")
        )
        detail = (
            ""
            if action is ReviewAction.PASS
            else f"{action.value} detail"
        )
        return json.dumps(
            {
                "run_id": request.task.run_id,
                "round_id": request.round_id,
                "action": action.value,
                "detail": detail,
                "requirement_ref": ref
                if action is ReviewAction.CHANGES
                else None,
            }
        )


class CountingFinalizer(StaticFinalizer):
    def __init__(self) -> None:
        super().__init__()
        self.integrate_calls = 0

    def integrate(self, frozen, final):
        self.integrate_calls += 1
        return super().integrate(frozen, final)


class CrashAfterIntegrationFinalizer(StaticFinalizer):
    def __init__(self) -> None:
        super().__init__()
        self.effect_count = 0
        self.calls = 0

    def integrate(self, frozen, final):
        self.calls += 1
        if self.effect_count == 0:
            self.effect_count = 1
            raise SystemExit("Abbruch nach Integrationswirkung")
        return super().integrate(frozen, final)


def _context(round_id: int) -> ControllerContext:
    git_base = VcsRef(ChangeMedium.GIT, f"g{round_id}-a")
    git_result = VcsRef(ChangeMedium.GIT, f"g{round_id}-b")
    beads = VcsRef(ChangeMedium.BEADS, f"b{round_id}")
    return ControllerContext(
        "Auftrag",
        CombinedDelta(
            DeltaScope.STEP,
            GitDelta(
                RefBoundary(git_base, git_result),
                (GitFileChange("M", "app.py"),),
                "+result = 1",
            ),
            BeadsDelta(RefBoundary(beads, beads), (), ""),
        ),
        RoundStatus(round_id, 5),
    )


def _task(run_id: str) -> RunTask:
    return RunTask(
        run_id,
        "Auftrag",
        ("bd:jbr.2",),
        Path("/work"),
        "write",
        acceptance_criteria=("Kriterium 1",),
    )


def _runtime(tmp_path, run_id, worker, reviewer, contexts):
    return RunRuntime(
        RunStore(tmp_path, run_id),
        worker,
        reviewer,
        StaticEvidenceCollector(tuple(contexts)),
        StaticFinalizer(),
    )


def test_fake_e2e_changes_then_pass_reaches_passed(
    tmp_path,
):
    worker = FakeWorker()
    reviewer = FakeReviewer([ReviewAction.CHANGES, ReviewAction.PASS])
    with _runtime(
        tmp_path,
        "run-e2e",
        worker,
        reviewer,
        [_context(1), _context(2)],
    ) as runtime:
        result = runtime.start(_task("run-e2e"), Limits())

    assert result.status == "passed"
    assert result.phase is Phase.PASSED
    assert result.round_id == 2
    assert worker.calls == reviewer.calls == 2
    artifacts = list((tmp_path / "run-e2e" / "artifacts").iterdir())
    assert len(artifacts) == 10
    assert (
        len(
            [
                path
                for path in artifacts
                if path.name.startswith("final-")
            ]
        )
        == 4
    )


def test_needs_decision_is_bound_and_resumes_same_run(tmp_path):
    worker = FakeWorker()
    reviewer = FakeReviewer(
        [ReviewAction.NEEDS_DECISION, ReviewAction.PASS]
    )
    with _runtime(
        tmp_path, "run-decision", worker, reviewer, [_context(1)]
    ) as runtime:
        waiting = runtime.start(_task("run-decision"), Limits())

    assert waiting.status == "waiting_decision"
    assert worker.calls == 1
    handoffs = list(
        (tmp_path / "run-decision" / "handoff").glob("*.json")
    )
    assert len(handoffs) == 1
    assert (
        json.loads(handoffs[0].read_text())["needed_decision"]
        == "NEEDS_DECISION detail"
    )

    with _runtime(
        tmp_path, "run-decision", worker, reviewer, [_context(1)]
    ) as resumed:
        result = resumed.resume("Die API bleibt kompatibel.")

    assert result.run_id == "run-decision"
    assert result.status == "passed"
    assert worker.calls == 1
    assert reviewer.calls == 2


def test_escalation_resume_rechecks_and_never_passes_by_itself(
    tmp_path,
):
    worker = FakeWorker()
    reviewer = FakeReviewer(
        [ReviewAction.ESCALATE, ReviewAction.CHANGES]
    )
    with _runtime(
        tmp_path,
        "run-escalate",
        worker,
        reviewer,
        [_context(1), _context(2)],
    ) as runtime:
        paused = runtime.start(_task("run-escalate"), Limits())
    assert paused.status == "paused_interactive"
    # ucq: der normale Reviewer-ESCALATE-Pfad (nicht nur der
    # Maschinen-Guard) schreibt ebenfalls eine Sitzungsuebergabe.
    handoffs = list(
        (tmp_path / "run-escalate" / "handoff").glob("*.json")
    )
    assert len(handoffs) == 1
    assert (
        json.loads(handoffs[0].read_text())["needed_decision"]
        == "ESCALATE detail"
    )

    with _runtime(
        tmp_path,
        "run-escalate",
        worker,
        reviewer,
        [_context(1), _context(2)],
    ) as resumed:
        result = resumed.resume("Dokumentation wurde ergaenzt.")

    assert result.status != "passed"
    assert result.round_id == 2
    assert reviewer.calls == 2
    assert worker.calls == 2


def test_protocol_attempts_are_bounded(tmp_path):
    invalid = "kein JSON"
    reviewer = FakeReviewer([invalid, invalid])
    with _runtime(
        tmp_path, "run-protocol", FakeWorker(), reviewer, [_context(1)]
    ) as runtime:
        result = runtime.start(
            _task("run-protocol"), Limits(protocol_attempts=1)
        )

    assert result.status == "paused_interactive"
    assert reviewer.calls == 2
    assert "protocol_attempts_exhausted" in result.detail
    handoffs = list(
        (tmp_path / "run-protocol" / "handoff").glob("*.json")
    )
    assert len(handoffs) == 1


def test_process_retries_are_bounded(tmp_path):
    worker = FailingBuilder()
    with _runtime(
        tmp_path,
        "run-process",
        worker,
        FakeReviewer([ReviewAction.PASS]),
        [_context(1)],
    ) as runtime:
        result = runtime.start(
            _task("run-process"), Limits(process_retries=1)
        )

    assert result.status == "paused_interactive"
    assert worker.calls == 2
    assert "process_retries_exhausted" in result.detail
    handoffs = list(
        (tmp_path / "run-process" / "handoff").glob("*.json")
    )
    assert len(handoffs) == 1


def test_empty_result_feedback_reruns_build_instead_of_reusing_artifact(
    tmp_path,
):
    """Regression: leere Rueckkopplung muss echt neu bauen.

    ``_feed_back_empty_result`` oeffnet einen neuen
    Worker-Zyklus, ohne ``round_id`` (Graph-Zustand) oder
    ``process_retry`` fortzuschreiben -- nur
    ``worker_attempt`` steigt. Bildete ``_operation()`` die
    operation_id weiterhin nur aus round_id/process_retry,
    waere sie identisch mit der des ersten, bereits
    gespeicherten Bauversuchs, und ``_progress_operation``
    haette dessen Artefakt einfach wiederverwendet, statt
    den Builder fuer den tatsaechlich neuen Versuch erneut
    aufzurufen.
    """
    empty_context = ControllerContext(
        "Auftrag",
        CombinedDelta(
            DeltaScope.STEP,
            GitDelta(
                RefBoundary(
                    VcsRef(ChangeMedium.GIT, "g1-a"),
                    VcsRef(ChangeMedium.GIT, "g1-a"),
                ),
                (),
                "",
            ),
            BeadsDelta(
                RefBoundary(
                    VcsRef(ChangeMedium.BEADS, "b1"),
                    VcsRef(ChangeMedium.BEADS, "b1"),
                ),
                (),
                "",
            ),
        ),
        RoundStatus(1, 5),
    )
    worker = FakeWorker()
    reviewer = FakeReviewer([ReviewAction.PASS])
    with _runtime(
        tmp_path, "run-empty-result", worker, reviewer, [empty_context]
    ) as runtime:
        result = runtime.start(
            _task("run-empty-result"), Limits(changes_rounds=1)
        )

    assert result.status == "paused_interactive"
    assert "empty_result_unresolved" in result.detail
    assert worker.calls == 2


def test_changes_rounds_are_bounded(tmp_path):
    reviewer = FakeReviewer(
        [ReviewAction.CHANGES, ReviewAction.CHANGES]
    )
    worker = FakeWorker()
    with _runtime(
        tmp_path,
        "run-rounds",
        worker,
        reviewer,
        [_context(1), _context(2)],
    ) as runtime:
        result = runtime.start(
            _task("run-rounds"), Limits(changes_rounds=1)
        )

    assert result.status == "paused_interactive"
    assert worker.calls == reviewer.calls == 2
    assert "changes_rounds_exhausted" in result.detail


def test_crash_after_effect_without_artifact_is_not_repeated(tmp_path):
    worker = FakeWorker(crash=True)
    reviewer = FakeReviewer([ReviewAction.PASS])
    with (
        _runtime(
            tmp_path, "run-uncertain", worker, reviewer, [_context(1)]
        ) as runtime,
        pytest.raises(SystemExit),
    ):
        runtime.start(_task("run-uncertain"), Limits())
    assert worker.calls == 1

    worker.crash = False
    with _runtime(
        tmp_path, "run-uncertain", worker, reviewer, [_context(1)]
    ) as resumed:
        result = resumed.resume()

    assert result.status == "uncertain"
    assert result.operation_id == "r0001-work-w0001-p0000-t0000"
    assert worker.calls == 1


def test_uncertain_effect_can_be_reconciled_explicitly(tmp_path):
    worker = FakeWorker(crash=True)
    reviewer = FakeReviewer([ReviewAction.PASS])
    with (
        _runtime(
            tmp_path, "run-reconcile", worker, reviewer, [_context(1)]
        ) as runtime,
        pytest.raises(SystemExit),
    ):
        runtime.start(_task("run-reconcile"), Limits())

    worker.crash = False
    with _runtime(
        tmp_path, "run-reconcile", worker, reviewer, [_context(1)]
    ) as resumed:
        uncertain = resumed.resume()
        result = resumed.reconcile(
            uncertain.operation_id, {"summary": "extern abgeglichen"}
        )

    assert result.status == "passed"
    assert worker.calls == 1


def test_saved_result_survives_crash_before_graph_checkpoint(
    tmp_path, monkeypatch
):
    worker = FakeWorker()
    reviewer = FakeReviewer([ReviewAction.PASS])
    original = RunStore.write_artifact
    crashed = False

    def write_then_crash(store, operation_id, value):
        nonlocal crashed
        original(store, operation_id, value)
        if "work-w" in operation_id and not crashed:
            crashed = True
            raise SystemExit("nach Persistenz")

    monkeypatch.setattr(RunStore, "write_artifact", write_then_crash)
    with (
        _runtime(
            tmp_path, "run-saved", worker, reviewer, [_context(1)]
        ) as runtime,
        pytest.raises(SystemExit),
    ):
        runtime.start(_task("run-saved"), Limits())

    monkeypatch.setattr(RunStore, "write_artifact", original)
    with _runtime(
        tmp_path, "run-saved", worker, reviewer, [_context(1)]
    ) as resumed:
        result = resumed.resume()

    assert result.status == "passed"
    assert worker.calls == 1


def test_saved_review_is_not_delivered_again_after_restart(
    tmp_path, monkeypatch
):
    worker = FakeWorker()
    reviewer = FakeReviewer([ReviewAction.PASS])
    original = RunStore.write_artifact
    crashed = False

    def write_then_crash(store, operation_id, value):
        nonlocal crashed
        original(store, operation_id, value)
        if "-review-" in operation_id and not crashed:
            crashed = True
            raise SystemExit("Review gesichert")

    monkeypatch.setattr(RunStore, "write_artifact", write_then_crash)
    with (
        _runtime(
            tmp_path, "run-review", worker, reviewer, [_context(1)]
        ) as runtime,
        pytest.raises(SystemExit),
    ):
        runtime.start(_task("run-review"), Limits())

    monkeypatch.setattr(RunStore, "write_artifact", original)
    with _runtime(
        tmp_path, "run-review", worker, reviewer, [_context(1)]
    ) as resumed:
        result = resumed.resume()

    assert result.status == "passed"
    assert reviewer.calls == 1
    messages = tmp_path / "run-review" / "messages"
    assert len(list(messages.iterdir())) == 1


def test_saved_integration_is_not_repeated_after_restart(
    tmp_path, monkeypatch
):
    worker = FakeWorker()
    reviewer = FakeReviewer([ReviewAction.PASS])
    finalizer = CountingFinalizer()
    original = RunStore.write_artifact

    def write_then_crash(store, operation_id, value):
        original(store, operation_id, value)
        if operation_id.startswith("final-integrate"):
            raise SystemExit("Integration gesichert")

    monkeypatch.setattr(RunStore, "write_artifact", write_then_crash)
    with (
        RunRuntime(
            RunStore(tmp_path, "run-final-resume"),
            worker,
            reviewer,
            StaticEvidenceCollector((_context(1),)),
            finalizer,
        ) as runtime,
        pytest.raises(SystemExit),
    ):
        runtime.start(_task("run-final-resume"), Limits())

    monkeypatch.setattr(RunStore, "write_artifact", original)
    with RunRuntime(
        RunStore(tmp_path, "run-final-resume"),
        worker,
        reviewer,
        StaticEvidenceCollector((_context(1),)),
        finalizer,
    ) as resumed:
        result = resumed.resume()

    assert result.status == "passed"
    assert result.phase is Phase.PASSED
    assert finalizer.integrate_calls == 1


def test_failed_final_verification_never_passes_and_can_resume(
    tmp_path,
):
    finalizer = StaticFinalizer(fail_verify=True)
    with RunRuntime(
        RunStore(tmp_path, "run-final-drift"),
        FakeWorker(),
        FakeReviewer([ReviewAction.PASS]),
        StaticEvidenceCollector((_context(1),)),
        finalizer,
    ) as runtime:
        paused = runtime.start(_task("run-final-drift"), Limits())

    assert paused.status == "paused_interactive"
    assert paused.phase is Phase.PAUSED_INTERACTIVE
    assert "final_verification_failed" in paused.detail
    # ucq (wiedereroeffnet): auch eine fehlgeschlagene Abschlusspruefung
    # muss eine Sitzungsuebergabe schreiben.
    handoffs = list(
        (tmp_path / "run-final-drift" / "handoff").glob("*.json")
    )
    assert len(handoffs) == 1

    finalizer.fail_verify = False
    with RunRuntime(
        RunStore(tmp_path, "run-final-drift"),
        FakeWorker(),
        FakeReviewer([]),
        StaticEvidenceCollector((_context(1),)),
        finalizer,
    ) as resumed:
        result = resumed.resume("Zieldrift wurde extern behoben.")

    assert result.status == "passed"
    assert result.phase is Phase.PASSED


def test_resume_rechecks_integration_after_crash_without_artifact(
    tmp_path,
):
    finalizer = CrashAfterIntegrationFinalizer()
    with (
        RunRuntime(
            RunStore(tmp_path, "run-effect-resume"),
            FakeWorker(),
            FakeReviewer([ReviewAction.PASS]),
            StaticEvidenceCollector((_context(1),)),
            finalizer,
        ) as runtime,
        pytest.raises(SystemExit),
    ):
        runtime.start(_task("run-effect-resume"), Limits())

    with RunRuntime(
        RunStore(tmp_path, "run-effect-resume"),
        FakeWorker(),
        FakeReviewer([]),
        StaticEvidenceCollector((_context(1),)),
        finalizer,
    ) as resumed:
        result = resumed.resume()

    assert result.status == "passed"
    assert finalizer.calls == 2
    assert finalizer.effect_count == 1


def test_failed_integration_pauses_and_writes_handoff(tmp_path):
    """ucq (wiedereroeffnet): eine fachlich fehlgeschlagene Integration
    (nicht nur ein Prozessabsturz) muss ebenfalls eine
    Sitzungsuebergabe schreiben, nicht nur pausieren."""
    finalizer = StaticFinalizer(fail_integrate=True)
    with RunRuntime(
        RunStore(tmp_path, "run-integrate-fail"),
        FakeWorker(),
        FakeReviewer([ReviewAction.PASS]),
        StaticEvidenceCollector((_context(1),)),
        finalizer,
    ) as runtime:
        result = runtime.start(_task("run-integrate-fail"), Limits())

    assert result.status == "paused_interactive"
    assert "integration_failed" in result.detail
    handoffs = list(
        (tmp_path / "run-integrate-fail" / "handoff").glob("*.json")
    )
    assert len(handoffs) == 1
    assert (
        json.loads(handoffs[0].read_text())["needed_decision"]
        == "fake integrate"
    )


def test_manual_relay_halts_executor_not_flow_and_continues(tmp_path):
    """Adapter manual: fehlt die Antwort des Boten, hält der Ausführer
    im selben Ablaufzustand an; nach abgelegter Antwort fährt dieselbe
    Operation weiter. Der Bote verbraucht kein Agentenbudget."""
    inbox = tmp_path / "inbox"
    reviewer = FakeReviewer([ReviewAction.PASS])
    with _runtime(
        tmp_path,
        "run-relay",
        ManualRelay(inbox, "worker"),
        reviewer,
        [_context(1)],
    ) as runtime:
        halted = runtime.start(_task("run-relay"), Limits())
        assert halted.status == "awaiting_input"
        assert halted.phase is Phase.WORKER_STEP
        (ask,) = inbox.glob("*.input.md")
        assert "Bauauftrag fuer Lauf run-relay" in ask.read_text()
        assert not (tmp_path / "run-relay" / "calls").exists()

        again = runtime.resume()
        assert again.status == "awaiting_input"
        assert len(list(inbox.glob("*.input.md"))) == 1

        answer = ask.with_name(
            ask.name.replace(".input.md", ".answer.md")
        )
        answer.write_text("Gebaut und geprüft.")
        with pytest.raises(RunResumeError, match="als Datei"):
            runtime.resume("Text statt Datei")
        result = runtime.resume()

    assert result.status == "passed"
    assert reviewer.calls == 1


def test_evidence_of_a_foreign_task_is_a_protocol_error():
    wrong = _context(1)
    with pytest.raises(AgentProtocolError, match="fremdem Auftrag"):
        runtime._validate_context(
            ControllerContext(
                "Fremder Auftrag", wrong.step_delta, wrong.round_status
            ),
            _task("run-x"),
            1,
        )
