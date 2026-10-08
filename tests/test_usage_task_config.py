"""wu0.3.8: usage_task-Bindung aus der echten Loop-Konfiguration.

``start_from_config`` laeuft unveraendert (Konfigurationsparser,
Manifest-Schreiber, ``RunRuntime._usage_attribution``); ersetzt wird
nur der Prozessaufbau (``_runtime``) durch Fake-Rollen. Kein Test
befuellt das Manifest von Hand.
"""

from __future__ import annotations

import inspect
import json

import pytest

from ki_dev.adapter.agent import (
    AgentBuildMode,
    AgentReviewer,
)
from ki_dev.adapter.executors import Effort
from ki_dev.adapter.executors.contract import TurnResult, TurnStatus
from ki_dev.repository_finalization import StaticFinalizer
from ki_dev.review_decision import (
    ReviewAction,
)
from ki_dev.run_store import RunStore
from ki_dev.runner.cli import (
    RunConfigError,
    resume_run,
    start_from_config,
)
from ki_dev.runner.runtime import (
    RunRuntime,
    StaticEvidenceCollector,
)
from ki_dev.runner.safety import CallLedger
from tests.test_runner_runtime import (
    FakeBuilder,
    FakeReviewer,
    _context,
)
from tests.test_runner_safety import USAGE, Executor

BINDING = {
    "bead_id": "ki-dev-ablauf-wu0.3.8",
    "task_revision": "rev-1",
    "family_id": "ki-dev-ablauf-wu0.3",
    "family_revision": "rev-1",
    "parent_bead_id": "ki-dev-ablauf-wu0.3",
}


def _config(tmp_path, **extra):
    path = tmp_path / "run.json"
    path.write_text(json.dumps({
        "task": "Auftrag",
        "acceptance_criteria": ["Kriterium 1"],
        "workdir": str(tmp_path),
        "access_profile": "write",
        "build": {},
        "review": {},
        **extra,
    }))
    return path


def _patch_runtime(monkeypatch, builder, reviewer=None):
    def build_runtime(_config, store, _projection):
        return RunRuntime(
            store,
            builder(),
            (
                reviewer(store.run_id)
                if reviewer
                else FakeReviewer([ReviewAction.PASS])
            ),
            StaticEvidenceCollector(
                tuple(_context(i) for i in range(1, 6))
            ),
            StaticFinalizer(),
        )

    monkeypatch.setattr(
        "ki_dev.runner.cli._runtime", build_runtime
    )


def _agent_builder(session_id="build-sess"):
    executor = Executor(
        TurnResult(
            TurnStatus.OK, 0, "fertig", "", (), 1.0, usage=dict(USAGE)
        )
    )
    return AgentBuildMode(executor, session_id, "model", Effort.LOW)


def _agent_reviewer(session_id):
    """Echter AgentReviewer mit eigener Sitzung und Verbrauch."""

    def make(run_id):
        answer = json.dumps({
            "run_id": run_id,
            "round_id": 1,
            "action": ReviewAction.PASS.value,
            "detail": "",
            "requirement_ref": None,
        })
        executor = Executor(
            TurnResult(
                TurnStatus.OK, 0, answer, "", (), 1.0,
                usage=dict(USAGE),
            )
        )
        return AgentReviewer(
            executor, session_id, "model", Effort.LOW
        )

    return make


def test_start_from_config_writes_usage_task_to_manifest(
    monkeypatch, tmp_path
):
    _patch_runtime(monkeypatch, FakeBuilder)
    runs = tmp_path / "runs"
    start_from_config(
        _config(tmp_path, usage_task=BINDING),
        run_id="run-a",
        runs_dir=runs,
    )
    manifest = RunStore(runs, "run-a").load_manifest()
    assert manifest["usage_task"] == BINDING
    assert manifest["configuration"]["usage_task"] == BINDING


def test_family_report_bundles_two_runs_from_real_config_path(
    monkeypatch, tmp_path
):
    _patch_runtime(monkeypatch, _agent_builder)
    runs = tmp_path / "runs"
    revisions = (("run-a", "rev-1"), ("run-b", "rev-2"))
    for run_id, task_revision in revisions:
        start_from_config(
            _config(
                tmp_path,
                usage_task={**BINDING, "task_revision": task_revision},
            ),
            run_id=run_id,
            runs_dir=runs,
        )
    # Ein dritter Lauf ohne Bindung gehoert nicht zur Familie.
    start_from_config(
        _config(tmp_path), run_id="run-c", runs_dir=runs
    )

    report = CallLedger(RunStore(runs, "run-a")).usage_report(
        family_id=BINDING["family_id"]
    )
    build_calls = [c for c in report.calls if c.total]
    assert {c.run_id for c in build_calls} == {"run-a", "run-b"}
    assert {c.run_id for c in report.calls} == {"run-a", "run-b"}
    assert all(c.attribution.complete for c in build_calls)
    assert all(
        c.attribution.family_id == BINDING["family_id"]
        for c in report.calls
    )
    assert report.total == sum(c.total for c in report.calls)
    assert len(build_calls) == 2
    assert {c.attribution.task_revision for c in build_calls} == {
        "rev-1",
        "rev-2",
    }
    # Revisionsfilter trennt weiterhin sauber.
    assert not CallLedger(RunStore(runs, "run-a")).usage_report(
        family_id="andere-familie"
    ).calls


def test_run_without_usage_task_stays_visibly_unattributed(
    monkeypatch, tmp_path
):
    _patch_runtime(monkeypatch, _agent_builder)
    runs = tmp_path / "runs"
    start_from_config(
        _config(tmp_path), run_id="run-c", runs_dir=runs
    )
    assert "usage_task" not in RunStore(runs, "run-c").load_manifest()
    calls = CallLedger(RunStore(runs, "run-c")).usage_report().calls
    assert calls
    assert all(not c.attribution.complete for c in calls)


@pytest.mark.parametrize(
    "usage_task",
    [
        {**BINDING, "typo": "x"},
        {},
        None,
        *({k: v for k, v in BINDING.items() if k != missing}
          for missing in (
              "bead_id", "task_revision", "family_id", "family_revision"
          )),
        "text",
        {**BINDING, "bead_id": ""},
        {**BINDING, "task_revision": 1},
        {**BINDING, "task_revision": "rev\n1"},
        {**BINDING, "family_id": "x" * 513},
        {**BINDING, "family_revision": "   "},
        {**BINDING, "parent_bead_id": None},
    ],
)
def test_usage_task_validation_stays_strict(tmp_path, usage_task):
    with pytest.raises(RunConfigError):
        start_from_config(
            _config(tmp_path, usage_task=usage_task),
            run_id="run-x",
            runs_dir=tmp_path / "runs",
        )


def test_rejected_usage_task_leaves_no_run_behind(tmp_path):
    runs = tmp_path / "runs"
    with pytest.raises(RunConfigError):
        start_from_config(
            _config(
                tmp_path,
                usage_task={**BINDING, "bead_id": "a\nb"},
            ),
            run_id="run-x",
            runs_dir=runs,
        )
    assert not (runs / "run-x").exists()


def test_max_length_value_is_accepted(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch, _agent_builder)
    runs = tmp_path / "runs"
    start_from_config(
        _config(
            tmp_path,
            usage_task={**BINDING, "family_id": "x" * 512},
        ),
        run_id="run-a",
        runs_dir=runs,
    )
    calls = CallLedger(RunStore(runs, "run-a")).usage_report().calls
    assert all(c.attribution.family_id == "x" * 512 for c in calls)


def test_unknown_top_level_field_is_still_rejected(tmp_path):
    with pytest.raises(RunConfigError, match="unbekannte"):
        start_from_config(
            _config(tmp_path, usage_tsk=BINDING),
            run_id="run-x",
            runs_dir=tmp_path / "runs",
        )


def test_parent_bead_id_is_optional(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch, _agent_builder)
    runs = tmp_path / "runs"
    binding = {
        k: v for k, v in BINDING.items() if k != "parent_bead_id"
    }
    start_from_config(
        _config(tmp_path, usage_task=binding),
        run_id="run-a",
        runs_dir=runs,
    )
    manifest = RunStore(runs, "run-a").load_manifest()
    assert manifest["usage_task"] == binding
    calls = CallLedger(RunStore(runs, "run-a")).usage_report().calls
    assert calls
    assert all(c.attribution.complete for c in calls if c.total)
    assert all(c.attribution.parent_bead_id is None for c in calls)


def test_resume_keeps_revisions_from_manifest(monkeypatch, tmp_path):
    reviewer = FakeReviewer(
        [ReviewAction.ESCALATE, ReviewAction.CHANGES]
    )

    def build_runtime(_config, store, _projection):
        return RunRuntime(
            store,
            _agent_builder(),
            reviewer,
            StaticEvidenceCollector(
                tuple(_context(i) for i in range(1, 6))
            ),
            StaticFinalizer(),
        )

    monkeypatch.setattr(
        "ki_dev.runner.cli._runtime", build_runtime
    )
    runs = tmp_path / "runs"
    paused = start_from_config(
        _config(tmp_path, usage_task=BINDING),
        run_id="run-a",
        runs_dir=runs,
    )
    assert paused.status == "paused_interactive"
    resume_run(
        "run-a", runs_dir=runs, answer="Dokumentation ergaenzt."
    )

    report = CallLedger(RunStore(runs, "run-a")).usage_report(
        family_id=BINDING["family_id"]
    )
    build_calls = [c for c in report.calls if c.total]
    assert len(build_calls) == 2  # vor und nach Resume
    assert {
        (c.attribution.task_revision, c.attribution.family_revision)
        for c in report.calls
    } == {(BINDING["task_revision"], BINDING["family_revision"])}
    manifest = RunStore(runs, "run-a").load_manifest()
    assert manifest["usage_task"] == BINDING


def test_changed_revision_is_a_new_run_not_a_manifest_rewrite(
    monkeypatch, tmp_path
):
    """Entscheidung B: kein Ueberschreiben, kein Resume-Wechsel."""
    _patch_runtime(monkeypatch, _agent_builder)
    runs = tmp_path / "runs"
    start_from_config(
        _config(tmp_path, usage_task=BINDING),
        run_id="run-a",
        runs_dir=runs,
    )
    with pytest.raises(Exception, match="existiert|widerspricht"):
        start_from_config(
            _config(
                tmp_path,
                usage_task={**BINDING, "task_revision": "rev-2"},
            ),
            run_id="run-a",
            runs_dir=runs,
        )
    assert (
        RunStore(runs, "run-a").load_manifest()["usage_task"]
        == BINDING
    )
    # Resume kennt keinen Revisionspfad (nur ID, Antwort, Abgleich).
    assert not {"usage_task", "task_revision"} & set(
        inspect.signature(resume_run).parameters
    )


# Je Turn: input 10 + output 20 + cache_read 100 + cache_creation 30.
TURN_TOKENS = 160


def _sessions(report):
    return {
        (c.attribution.role, c.attribution.session_id)
        for c in report.calls
        if c.total
    }


def test_revision_change_via_new_run_keeps_family_cumulative(
    monkeypatch, tmp_path
):
    runs = tmp_path / "runs"
    rev2 = {**BINDING, "task_revision": "rev-2"}
    _patch_runtime(
        monkeypatch,
        lambda: _agent_builder("build-a"),
        _agent_reviewer("review-a"),
    )
    start_from_config(
        _config(tmp_path, usage_task=BINDING),
        run_id="run-a",
        runs_dir=runs,
    )
    a_before = CallLedger(RunStore(runs, "run-a")).usage_report()
    manifest_a = RunStore(runs, "run-a").load_manifest()

    # Neuer Lauf: neue Bau- und Review-Sitzungen (Entscheidung B).
    _patch_runtime(
        monkeypatch,
        lambda: _agent_builder("build-b"),
        _agent_reviewer("review-b"),
    )
    start_from_config(
        _config(tmp_path, usage_task=rev2),
        run_id="run-b",
        runs_dir=runs,
    )

    # Alter Lauf: Manifest, Calls und Bilanz unveraendert.
    assert RunStore(runs, "run-a").load_manifest() == manifest_a
    a_after = CallLedger(RunStore(runs, "run-a")).usage_report()
    assert a_after == a_before
    assert {c.attribution.task_revision for c in a_after.calls} == {
        "rev-1"
    }
    assert _sessions(a_after) == {
        ("build", "build-a"),
        ("review", "review-a"),
    }
    assert a_after.total == 2 * TURN_TOKENS

    # Neuer Lauf: eigene run_id, Revision, Sitzungen und Bilanz.
    b_report = CallLedger(RunStore(runs, "run-b")).usage_report()
    assert RunStore(runs, "run-b").load_manifest()["usage_task"] == rev2
    assert {c.run_id for c in b_report.calls} == {"run-b"}
    assert {c.attribution.task_revision for c in b_report.calls} == {
        "rev-2"
    }
    assert _sessions(b_report) == {
        ("build", "build-b"),
        ("review", "review-b"),
    }
    assert b_report.total == 2 * TURN_TOKENS

    # Familie: kumulativ ueber beide Revisionen, ohne Doppelzaehlung.
    family = CallLedger(RunStore(runs, "run-b")).usage_report(
        family_id=BINDING["family_id"]
    )
    assert {c.run_id for c in family.calls} == {"run-a", "run-b"}
    assert family.total == 4 * TURN_TOKENS
    only_rev2 = CallLedger(RunStore(runs, "run-b")).usage_report(
        family_id=BINDING["family_id"], family_revision="rev-2"
    )
    assert only_rev2.total == 0  # family_revision blieb rev-1
