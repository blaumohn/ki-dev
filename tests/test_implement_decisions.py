"""Entscheidung des Menschen: Auftrag im Bead ändern, ``resume``.

Der geänderte Auftrag ersetzt die Kopie im Lauf; Review, Umsetzer und
die Bindung von ``fix`` folgen ihm. Der Fall aus dem README: der Test
hält das alte Verhalten fest, AC2 verbietet zunächst, ihn zu ändern.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from ki_dev.adapter.contract import WorkReport
from ki_dev.flow_ops.implement.decisions import (
    decision_document,
    prompt_text,
    summary,
)
from ki_dev.flow_ops.implement.machine import Limits
from ki_dev.flow_ops.implement.runtime import (
    RunResumeError,
    RunRuntime,
    StaticEvidenceCollector,
)
from ki_dev.repository_finalization import (
    FinalizationFailure,
    StaticFinalizer,
)
from ki_dev.run_store import RunStore
from tests.test_runner_runtime import (
    FakeReviewer,
    FakeWorker,
    _context,
    _runtime,
    _task,
)

OLD = (
    "is_newer('1.10.0', '1.9.0') is True",
    "test_version.py stays unchanged",
)
NEW = (OLD[0], "second assert becomes is_newer('1.10.0', '1.9.0')")


class RecordingWorker(FakeWorker):
    def __init__(self) -> None:
        super().__init__()
        self.prompts: list[str] = []

    def work(self, request):
        self.prompts.append(request.prompt)
        return super().work(request)


class RecordingReviewer(FakeReviewer):
    def __init__(self, actions) -> None:
        super().__init__(actions)
        self.prompts: list[str] = []

    def review(self, request):
        self.prompts.append(request.prompt)
        return super().review(request)


def test_worker_decision_resumes_in_new_runtime(tmp_path):
    class DecidingWorker(RecordingWorker):
        def work(self, request):
            report = super().work(request)
            if self.calls == 1:
                return WorkReport(
                    "Darf AC2 geändert werden?", "needs_decision"
                )
            return report

    worker = DecidingWorker()
    reviewer = FakeReviewer(["PASS"])
    with _runtime(tmp_path, "worker", worker, reviewer, []) as runtime:
        result = runtime.start(_version_task("worker"), Limits())
        assert result.status == "waiting_decision"
    assert reviewer.calls == 0

    with _runtime(
        tmp_path, "worker", worker, reviewer, [_context(1)]
    ) as runtime:
        result = runtime.resume("AC2 darf angepasst werden")
    assert result.status == "passed"
    assert worker.calls == 2
    assert "AC2 darf angepasst werden" in worker.prompts[1]


def _version_task(run_id: str, criteria=OLD):
    return replace(_task(run_id), acceptance_criteria=criteria)


def test_changed_bead_reaches_review_worker_and_binding(tmp_path):
    """decision → Bead geändert → resume ohne Antwort → fix (AC2)
    gegen das neue AC2 → Runde 2 → PASS."""
    worker = RecordingWorker()
    reviewer = RecordingReviewer(["decision", ("fix", "AC2"), "PASS"])
    contexts = [_context(1), _context(2)]
    with _runtime(tmp_path, "v", worker, reviewer, contexts) as runtime:
        halted = runtime.start(_version_task("v"), Limits())
        assert halted.status == "waiting_decision"

        result = runtime.resume(task=_version_task("v", NEW))

    assert result.status == "passed"
    assert "AC2 neu: second assert" in reviewer.prompts[1]
    assert f"AC2 alt: {OLD[1]}" in reviewer.prompts[1]
    assert f"- AC2: {NEW[1]}" in reviewer.prompts[1]
    assert f"- AC2: {NEW[1]}" in worker.prompts[1]
    assert "AC2 neu: second assert" in worker.prompts[1]
    record = RunStore(tmp_path, "v").load_record()
    assert record["data"]["task"]["acceptance_criteria"] == list(NEW)


def test_answer_without_bead_change_reaches_worker_after_fix(tmp_path):
    """``--answer`` für alles, was nicht in den Bead gehört: es bleibt
    über das ``fix`` hinaus bei Review und Umsetzer."""
    worker = RecordingWorker()
    reviewer = RecordingReviewer(["decision", "fix", "PASS"])
    contexts = [_context(1), _context(2)]
    with _runtime(tmp_path, "a", worker, reviewer, contexts) as runtime:
        runtime.start(_version_task("a"), Limits())
        result = runtime.resume("Tests mit pytest ausführen")

    assert result.status == "passed"
    assert "Antwort: Tests mit pytest ausführen" in reviewer.prompts[1]
    assert "Antwort: Tests mit pytest ausführen" in worker.prompts[1]
    assert "Antwort: Tests mit pytest" in reviewer.prompts[2]


def test_resume_without_decision_is_refused(tmp_path):
    """Bead unverändert, keine Antwort: dieselbe Frage stünde erneut
    an, ``resume`` weist ab und der Lauf wartet weiter."""
    reviewer = FakeReviewer(["decision"])
    with _runtime(
        tmp_path, "w", FakeWorker(), reviewer, [_context(1)]
    ) as runtime:
        runtime.start(_version_task("w"), Limits())
        with pytest.raises(RunResumeError, match="Bead"):
            runtime.resume(task=_version_task("w"))
        assert runtime.result().status == "waiting_decision"
    assert reviewer.calls == 1


def test_prompt_and_history_name_added_and_dropped_criteria():
    old = _version_task("x")
    new = replace(
        old, acceptance_criteria=("neu 1",), task="anderer Auftrag"
    )
    document = decision_document(old, new, None, 1)

    text = prompt_text([document])

    assert "AC1 alt: is_newer" in text and "AC1 neu: neu 1" in text
    assert "AC2 entfaellt: test_version.py" in text
    assert "Auftragstext geaendert" in text
    assert summary(document) == (
        "AC1 geändert; AC2 geändert; Auftragstext geändert"
    )
    assert prompt_text([]) == "keine"


class BeadsCollector(StaticEvidenceCollector):
    """Grenzen mit Beads-Stand wie RepositoryEvidenceCollector; der
    Mensch hat Beads geändert, der Stand ist jetzt ``b2``."""

    def prepare(self, task, round_id):
        del task
        return {
            "git": {"medium": "git", "value": f"g{round_id}-a"},
            "beads": {"medium": "beads", "value": f"b{round_id}"},
        }

    def adopt_beads(self, task, refs):
        del task
        return {**refs, "beads": {"medium": "beads", "value": "b2"}}


def _beads_runtime(tmp_path, run_id, reviewer, collector):
    return RunRuntime(
        RunStore(tmp_path, run_id),
        FakeWorker(),
        reviewer,
        collector,
        StaticFinalizer(),
    )


def test_bead_change_moves_beads_boundaries_of_the_run(tmp_path):
    """Die Änderung des Menschen ist kein Ergebnis des Laufs: Basis
    und geprüfter Stand rücken auf den neuen Beads-Stand."""
    collector = BeadsCollector((_context(1), _context(2)))
    reviewer = FakeReviewer(["decision", ("fix", "AC2"), "PASS"])
    with _beads_runtime(tmp_path, "b", reviewer, collector) as runtime:
        runtime.start(_version_task("b"), Limits())
        before = RunStore(tmp_path, "b").load_record()["data"]
        assert before["run_base"]["beads"]["value"] == "b1"

        result = runtime.resume(task=_version_task("b", NEW))

    assert result.status == "passed"
    data = RunStore(tmp_path, "b").load_record()["data"]
    assert data["run_base"]["beads"]["value"] == "b2"
    assert data["run_base"]["git"] == before["run_base"]["git"]


def test_answer_adopts_beads_change_of_the_human(tmp_path):
    """Regression eigenprobe-641: ein neuer Bead in der Pause beendet
    den Lauf nicht. Die Antwort übernimmt den Stand für alle Grenzen,
    Git bleibt unberührt."""
    collector = BeadsCollector((_context(1),))
    reviewer = FakeReviewer(["decision", "PASS"])
    with _beads_runtime(tmp_path, "f", reviewer, collector) as runtime:
        runtime.start(_version_task("f"), Limits())
        before = RunStore(tmp_path, "f").load_record()["data"]

        result = runtime.resume("Neuer Bead gehört nicht zum Auftrag")

    assert result.status == "passed"
    data = RunStore(tmp_path, "f").load_record()["data"]
    assert data["run_base"]["beads"]["value"] == "b2"
    assert data["run_base"]["git"] == before["run_base"]["git"]


def test_refused_freeze_halts_and_answer_retries_it(tmp_path):
    """Beads während eines Turns geändert: Halt statt ``error``, kein
    neuer Worker und kein neues Review."""

    class OnceRefusing(StaticFinalizer):
        refused = False

        def freeze(self, **kwargs):
            if not self.refused:
                self.refused = True
                raise FinalizationFailure("Beads-Stand abweichend")
            return super().freeze(**kwargs)

    worker = FakeWorker()
    reviewer = FakeReviewer(["PASS"])
    with RunRuntime(
        RunStore(tmp_path, "z"),
        worker,
        reviewer,
        BeadsCollector((_context(1),)),
        OnceRefusing(),
    ) as runtime:
        halted = runtime.start(_version_task("z"), Limits())
        assert halted.status == "paused_interactive"
        assert "finalization_refused" in halted.detail

        result = runtime.resume("Stand übernehmen")

    assert result.status == "passed"
    assert worker.calls == 1
    assert reviewer.calls == 1
