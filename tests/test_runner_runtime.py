from __future__ import annotations

import json
from pathlib import Path

import pytest

from ki_dev.adapter.contract import (
    RunTask,
    WorkReport,
)
from ki_dev.adapter.manual import Inbox, ManualRelay
from ki_dev.adapter.registry import executor_specs
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
from ki_dev.flow_ops.implement import ops as implement_ops
from ki_dev.flow_ops.implement.machine import IMPLEMENT, Limits, Phase
from ki_dev.flow_ops.implement.runtime import (
    RunResumeError,
    RunRuntime,
    StaticEvidenceCollector,
)
from ki_dev.repository_finalization import StaticFinalizer
from ki_dev.run_store import RunStore
from ki_dev.runner.review_output import AgentProtocolError
from tests.executor_specs import LOCAL

SPECS = executor_specs()


class FakeWorker:
    spec = LOCAL

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
    spec = LOCAL

    def __init__(self, actions) -> None:
        self.actions = list(actions)
        self.calls = 0

    def review(self, request):
        item = self.actions[self.calls]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        if item not in IMPLEMENT.review_events() and isinstance(
            item, str
        ):
            return item  # Rohtext, z. B. Protokollfehler
        action, ref = (
            item if isinstance(item, tuple) else (item, "AC1")
        )
        detail = (
            ""
            if action == "PASS"
            else f"{action} detail"
        )
        return json.dumps(
            {
                "run_id": request.task.run_id,
                "round_id": request.round_id,
                "event": action,
                "detail": detail,
                "requirement_ref": ref
                if action == "fix"
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
    reviewer = FakeReviewer(["fix", "PASS"])
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
        ["decision", "PASS"]
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
        == "decision detail"
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
        ["escalate", "fix"]
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
    # Die Pause hält den Lauf, nicht den Ablauf: er steht noch dort,
    # wo eskaliert wurde, und setzt dort fort.
    assert paused.phase is Phase.CONTROLLER_STEP
    assert paused.detail == "escalate detail"
    # ucq: der normale Reviewer-ESCALATE-Pfad (nicht nur der
    # Maschinen-Guard) schreibt ebenfalls eine Sitzungsuebergabe.
    handoffs = list(
        (tmp_path / "run-escalate" / "handoff").glob("*.json")
    )
    assert len(handoffs) == 1
    assert (
        json.loads(handoffs[0].read_text())["needed_decision"]
        == "escalate detail"
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
        FakeReviewer(["PASS"]),
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
    reviewer = FakeReviewer(["PASS"])
    with _runtime(
        tmp_path, "run-empty-result", worker, reviewer, [empty_context]
    ) as runtime:
        result = runtime.start(
            _task("run-empty-result"), Limits(changes_rounds=1)
        )

    assert result.status == "paused_interactive"
    assert "empty_result_unresolved" in result.detail
    assert worker.calls == 2


def test_empty_correction_with_run_result_goes_to_review(tmp_path):
    """Regression eigenprobe-641 (ki-dev-ablauf-hm76): nach ``fix``
    ändert der Worker nichts, weil der Stand schon passt. Statt
    desselben Bauauftrags prüft das Review den Stand erneut."""
    unchanged = VcsRef(ChangeMedium.GIT, "g1-b")
    beads = VcsRef(ChangeMedium.BEADS, "b1")
    round_one = _context(1)
    empty_round_two = ControllerContext(
        "Auftrag",
        CombinedDelta(
            DeltaScope.STEP,
            GitDelta(RefBoundary(unchanged, unchanged), (), ""),
            BeadsDelta(RefBoundary(beads, beads), (), ""),
        ),
        RoundStatus(2, 5),
        run_delta=CombinedDelta(
            DeltaScope.RUN,
            round_one.step_delta.git,
            round_one.step_delta.beads,
        ),
    )
    worker = FakeWorker()
    reviewer = FakeReviewer(["fix", "PASS"])
    with _runtime(
        tmp_path,
        "run-empty-fix",
        worker,
        reviewer,
        [round_one, empty_round_two],
    ) as runtime:
        result = runtime.start(_task("run-empty-fix"), Limits())

    assert result.status == "passed"
    assert worker.calls == 2
    assert reviewer.calls == 2


def test_changes_rounds_are_bounded(tmp_path):
    reviewer = FakeReviewer(
        ["fix", "fix"]
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
    reviewer = FakeReviewer(["PASS"])
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
    assert result.operation_id == "r0001-work-w0001-p0000-t0000-d0000"
    assert worker.calls == 1


def test_uncertain_effect_can_be_reconciled_explicitly(tmp_path):
    worker = FakeWorker(crash=True)
    reviewer = FakeReviewer(["PASS"])
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
            uncertain.operation_id,
            {
                "summary": "extern abgeglichen",
                "event": "worker_completed",
            },
        )

    assert result.status == "passed"
    assert worker.calls == 1


def test_saved_result_survives_crash_before_graph_checkpoint(
    tmp_path, monkeypatch
):
    worker = FakeWorker()
    reviewer = FakeReviewer(["PASS"])
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
    reviewer = FakeReviewer(["PASS"])
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
    reviewer = FakeReviewer(["PASS"])
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
        FakeReviewer(["PASS"]),
        StaticEvidenceCollector((_context(1),)),
        finalizer,
    ) as runtime:
        paused = runtime.start(_task("run-final-drift"), Limits())

    assert paused.status == "paused_interactive"
    assert paused.phase is Phase.VERIFY_FINAL_RESULT
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
            FakeReviewer(["PASS"]),
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


class BrokenIntegrationFinalizer(StaticFinalizer):
    def integrate(self, *_):
        raise RuntimeError("Git kaputt")


def test_failed_operation_sends_its_declared_failure_event(tmp_path):
    """Das Scheitern einer Operation ist das Ereignis, das sie im
    Ablauf nennt (`failure`): bei der Integration finalization_error."""
    with RunRuntime(
        RunStore(tmp_path, "run-broken-integration"),
        FakeWorker(),
        FakeReviewer(["PASS"]),
        StaticEvidenceCollector((_context(1),)),
        BrokenIntegrationFinalizer(),
    ) as runtime:
        result = runtime.start(
            _task("run-broken-integration"), Limits()
        )

    assert result.status == "error"
    assert result.phase is Phase.ERROR
    events = [
        event
        for event in RunStore(
            tmp_path, "run-broken-integration"
        ).load_events()
        if event["region"] == "ablauf"
    ]
    assert events[-1]["event"] == "finalization_error"
    assert events[-1]["state"] == "fast_forward_integrate"


def test_failed_integration_pauses_and_writes_handoff(tmp_path):
    """ucq (wiedereroeffnet): eine fachlich fehlgeschlagene Integration
    (nicht nur ein Prozessabsturz) muss ebenfalls eine
    Sitzungsuebergabe schreiben, nicht nur pausieren."""
    finalizer = StaticFinalizer(fail_integrate=True)
    with RunRuntime(
        RunStore(tmp_path, "run-integrate-fail"),
        FakeWorker(),
        FakeReviewer(["PASS"]),
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
    reviewer = FakeReviewer(["PASS"])
    with _runtime(
        tmp_path,
        "run-relay",
        ManualRelay(Inbox(inbox), "worker", SPECS["inbox"]),
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
        with pytest.raises(
            RunResumeError, match="Laufstatus awaiting_input"
        ):
            runtime.resume("Text statt Datei")
        result = runtime.resume()

    assert result.status == "passed"
    assert reviewer.calls == 1


def test_evidence_of_a_foreign_task_is_a_protocol_error():
    wrong = _context(1)
    with pytest.raises(AgentProtocolError, match="fremdem Auftrag"):
        implement_ops._validate_context(
            ControllerContext(
                "Fremder Auftrag", wrong.step_delta, wrong.round_status
            ),
            _task("run-x"),
            1,
        )


def test_record_is_the_only_run_state(tmp_path):
    """Kein Checkpoint neben dem Datensatz: Lauf-Maschine, offene
    Operation und Ablaufzustand stehen in ``record.json``; der
    Ablaufzustand genau einmal (Laufdaten), nicht auch in der
    Konfiguration der Lauf-Maschine."""
    with _runtime(
        tmp_path,
        "run-record",
        FakeWorker(),
        FakeReviewer(["decision"]),
        [_context(1)],
    ) as runtime:
        waiting = runtime.start(_task("run-record"), Limits())

    record = json.loads(
        (tmp_path / "run-record" / "record.json").read_text()
    )
    assert waiting.status == "waiting_decision"
    assert sorted(record["run"]["state"]) == [
        "halt", "idle", "lauf", "operation", "waiting",
    ]
    assert record["pending"] is None
    assert record["data"]["run_state"]["state"]["phase"] == (
        "waiting_decision"
    )
    assert not list((tmp_path / "run-record").glob("*.sqlite*"))


def test_answer_after_process_end_continues_in_a_new_runtime(tmp_path):
    """Halt beendet den Prozess; ein neuer Aufruf liest den Datensatz
    und setzt mit der Antwort fort."""
    reviewer = FakeReviewer(["decision", "PASS"])
    with _runtime(
        tmp_path, "run-answer", FakeWorker(), reviewer, [_context(1)]
    ) as runtime:
        runtime.start(_task("run-answer"), Limits())

    with _runtime(
        tmp_path, "run-answer", FakeWorker(), reviewer, [_context(1)]
    ) as resumed:
        with pytest.raises(
            RunResumeError, match="wartet auf eine Entscheidung"
        ):
            resumed.resume()
        result = resumed.resume("Ablage A")

    assert result.status == "passed"


def test_relay_answer_after_process_end_continues_in_a_new_runtime(
    tmp_path,
):
    """Bote (inbox): Halt in awaiting_input, Prozessende, Antwortdatei,
    neuer Aufruf fährt dieselbe Operation weiter."""
    inbox = tmp_path / "inbox"
    relay = ManualRelay(Inbox(inbox), "worker", SPECS["inbox"])
    reviewer = FakeReviewer(["PASS"])
    with _runtime(
        tmp_path, "run-relay-new", relay, reviewer, [_context(1)]
    ) as runtime:
        halted = runtime.start(_task("run-relay-new"), Limits())
    (ask,) = inbox.glob("*.input.md")
    answer = ask.with_name(ask.name.replace(".input.md", ".answer.md"))
    answer.write_text("Gebaut.")

    with _runtime(
        tmp_path, "run-relay-new", relay, reviewer, [_context(1)]
    ) as resumed:
        result = resumed.resume()

    assert halted.status == "awaiting_input"
    assert result.status == "passed"


def test_a_second_writer_is_rejected(tmp_path):
    with _runtime(
        tmp_path, "run-lock", FakeWorker(), FakeReviewer([]), []
    ), pytest.raises(RunResumeError, match="bereits"):
        _runtime(
            tmp_path, "run-lock", FakeWorker(), FakeReviewer([]), []
        )


def test_langgraph_checkpoint_gets_a_clear_message(tmp_path):
    run_dir = tmp_path / "run-old"
    run_dir.mkdir()
    (run_dir / "checkpoints.sqlite").write_bytes(b"")
    with _runtime(
        tmp_path, "run-old", FakeWorker(), FakeReviewer([]), []
    ) as runtime, pytest.raises(RunResumeError, match="LangGraph"):
        runtime.resume()


def test_manual_review_waits_for_a_new_answer_after_protocol_error(
    tmp_path,
):
    """Eine ungültige Antwort des Boten verbraucht genau einen
    Protokollversuch; der nächste Versuch wartet auf eine neue Datei,
    statt die abgewiesene erneut zu lesen."""
    inbox = tmp_path / "inbox"
    with _runtime(
        tmp_path,
        "run-relay-review",
        FakeWorker(),
        ManualRelay(Inbox(inbox), "review", SPECS["inbox"]),
        [_context(1)],
    ) as runtime:
        halted = runtime.start(_task("run-relay-review"), Limits())
        assert halted.status == "awaiting_input"
        (first,) = inbox.glob("*.input.md")
        first.with_name(
            first.name.replace(".input.md", ".answer.md")
        ).write_text("kein JSON")
        again = runtime.resume()

    assert again.status == "awaiting_input"
    assert again.phase is Phase.CONTROLLER_STEP
    asks = sorted(inbox.glob("*.input.md"))
    assert len(asks) == 2
    assert first in asks


def test_retry_after_protocol_error_names_the_violation(tmp_path):
    """Die Wiederholung erhält den Vertragsfehler der abgewiesenen
    Antwort; derselbe Prompt ergäbe dieselbe Antwort (echter Lauf:
    viermal ``requirement_ref`` bei ``decision``)."""
    inbox = tmp_path / "inbox"
    line = "Vertragsfehler deiner vorigen Antwort: "
    with _runtime(
        tmp_path,
        "run-relay-retry",
        FakeWorker(),
        ManualRelay(Inbox(inbox), "review", SPECS["inbox"]),
        [_context(1)],
    ) as runtime:
        runtime.start(_task("run-relay-retry"), Limits())
        (first,) = inbox.glob("*.input.md")
        first.with_name(
            first.name.replace(".input.md", ".answer.md")
        ).write_text(
            '{"run_id": "run-relay-retry", "round_id": 1, '
            '"event": "decision", "detail": "Test widerspricht", '
            '"requirement_ref": "AC1"}'
        )
        runtime.resume()

    (second,) = set(inbox.glob("*.input.md")) - {first}
    assert f"{line}keiner\n" in first.read_text()
    violation = (
        "requirement_ref: ist außer bei CHANGES-Ereignissen null"
    )
    assert f"{line}{violation}\n" in second.read_text()
