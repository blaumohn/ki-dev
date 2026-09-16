from __future__ import annotations

import json
from pathlib import Path

import pytest
from langgraph.checkpoint.base import uuid6

from ki_dev.loop import LoopTask, ReviewAction
from ki_dev.loop_cli import LoopConfigError, status_run
from ki_dev.loop_runtime import (
    LoopResumeError,
    LoopRuntime,
    StaticEvidenceCollector,
)
from ki_dev.machine import Limits, Phase
from ki_dev.repository_finalization import StaticFinalizer
from ki_dev.run_store import RunStore, RunStoreError
from tests.test_loop_runtime import FakeBuilder, FakeReviewer, _context


def _task(run_id: str) -> LoopTask:
    return LoopTask(
        run_id,
        "Auftrag",
        ("bd:jbr.2",),
        Path("/work"),
        "write",
        acceptance_criteria=("Kriterium 1",),
    )


def _sidecar_free_snapshot(root: Path) -> dict[str, bytes]:
    """Dateibaum ohne SQLite-Sidecars (``-wal``/``-shm``).

    Deren Vorhandensein ist kein Fehler (p0h.1: "Kein byteidentischer
    gesamter Dateibaum als stilles Ersatzkriterium" / "notwendige
    Sidecars alleine lassen Tests nicht fehlschlagen").
    """
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.name.endswith(("-wal", "-shm"))
    }


def _add_configuration(tmp_path: Path, run_id: str) -> None:
    manifest_path = tmp_path / run_id / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["configuration"] = {}
    manifest_path.write_text(json.dumps(manifest))


def test_status_reads_persisted_state_without_advancing(tmp_path):
    builder = FakeBuilder()
    reviewer = FakeReviewer(
        [ReviewAction.NEEDS_DECISION, ReviewAction.PASS]
    )
    with LoopRuntime(
        RunStore(tmp_path, "run-status"),
        builder,
        reviewer,
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    ) as runtime:
        waiting = runtime.start(_task("run-status"), Limits())

    assert waiting.status == "waiting_decision"
    _add_configuration(tmp_path, "run-status")

    first = status_run("run-status", runs_dir=tmp_path)
    second = status_run("run-status", runs_dir=tmp_path)

    assert first.status == "waiting_decision"
    assert first.phase is Phase.WAITING_DECISION
    assert first.round_id == waiting.round_id
    assert second == first
    assert builder.calls == 1
    assert reviewer.calls == 1


def test_status_reports_missing_run_clearly(tmp_path):
    with pytest.raises(RunStoreError):
        status_run("does-not-exist", runs_dir=tmp_path)


def test_status_reports_manifest_without_configuration(tmp_path):
    with LoopRuntime(
        RunStore(tmp_path, "run-no-config"),
        FakeBuilder(),
        FakeReviewer([ReviewAction.PASS]),
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    ) as runtime:
        runtime.start(_task("run-no-config"), Limits())

    with pytest.raises(LoopConfigError):
        status_run("run-no-config", runs_dir=tmp_path)


def test_status_reads_live_run_while_writer_holds_wal_open(
    tmp_path,
):
    builder = FakeBuilder()
    reviewer = FakeReviewer(
        [ReviewAction.NEEDS_DECISION, ReviewAction.PASS]
    )
    runtime = LoopRuntime(
        RunStore(tmp_path, "run-live"),
        builder,
        reviewer,
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    )
    try:
        waiting = runtime.start(_task("run-live"), Limits())
        run_dir = tmp_path / "run-live"
        assert (run_dir / "checkpoints.sqlite-wal").exists()
        _add_configuration(tmp_path, "run-live")

        result = status_run("run-live", runs_dir=tmp_path)

        assert result.status == "waiting_decision"
        assert result.phase is waiting.phase
        assert result.round_id == waiting.round_id
        assert builder.calls == 1
        assert reviewer.calls == 1
    finally:
        runtime.close()


def test_status_reads_crash_state_with_wal_but_no_shm(tmp_path):
    builder = FakeBuilder()
    reviewer = FakeReviewer(
        [ReviewAction.NEEDS_DECISION, ReviewAction.PASS]
    )
    runtime = LoopRuntime(
        RunStore(tmp_path, "run-crash"),
        builder,
        reviewer,
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    )
    run_dir = tmp_path / "run-crash"
    waiting = runtime.start(_task("run-crash"), Limits())
    main_bytes = (run_dir / "checkpoints.sqlite").read_bytes()
    wal_bytes = (run_dir / "checkpoints.sqlite-wal").read_bytes()
    runtime.close()
    _add_configuration(tmp_path, "run-crash")

    # Nach einem Absturz kann eine WAL-Datei ohne zugehoerige SHM-Datei
    # zurueckbleiben; ein sauberes runtime.close() raeumt beides auf,
    # daher wird der Zustand hier gezielt aus den waehrend des offenen
    # Laufs erfassten Bytes rekonstruiert.
    (run_dir / "checkpoints.sqlite").write_bytes(main_bytes)
    (run_dir / "checkpoints.sqlite-wal").write_bytes(wal_bytes)
    assert not (run_dir / "checkpoints.sqlite-shm").exists()

    result = status_run("run-crash", runs_dir=tmp_path)

    assert result.status == "waiting_decision"
    assert result.phase is waiting.phase
    assert result.round_id == waiting.round_id

    # Das Lesen einer WAL ohne vorhandene SHM-Datei braucht deren
    # Neuanlage (SQLites eigene Koordination fuer den WAL-Index); das
    # ist ein notwendiger Sidecar und kein stiller Fehlschlag-Grund
    # (p0h.1). Hauptdatei und WAL selbst bleiben dabei byteidentisch --
    # das Lesen veraendert nie den eigentlichen persistierten Inhalt.
    assert (run_dir / "checkpoints.sqlite").read_bytes() == main_bytes
    assert (
        run_dir / "checkpoints.sqlite-wal"
    ).read_bytes() == wal_bytes


def test_status_read_is_consistent_despite_concurrent_checkpoint(
    tmp_path, monkeypatch
):
    """Ein Checkpoint mitten in unserer eigenen Momentaufnahme darf nie
    zu einer Mischung aus zwei Schreibvorgaengen fuehren (re0)."""
    import ki_dev.loop_runtime as loop_runtime_module

    builder = FakeBuilder()
    reviewer = FakeReviewer(
        [ReviewAction.NEEDS_DECISION, ReviewAction.PASS]
    )
    runtime = LoopRuntime(
        RunStore(tmp_path, "run-race"),
        builder,
        reviewer,
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    )
    waiting = runtime.start(_task("run-race"), Limits())
    _add_configuration(tmp_path, "run-race")

    triggered = {"done": False}

    def racing_snapshot(source, destination):
        target = loop_runtime_module.sqlite3.connect(destination)

        def concurrent_write_mid_copy(status, remaining, total):
            del status, total
            if not triggered["done"] and remaining > 0:
                triggered["done"] = True
                # Ein weiterer Schreibvorgang samt Checkpoint laeuft,
                # waehrend unsere eigene Momentaufnahme bereits eine
                # Seite kopiert hat.
                runtime.resume("weiter")

        try:
            source.backup(
                target, pages=1, progress=concurrent_write_mid_copy
            )
        finally:
            target.close()

    monkeypatch.setattr(
        loop_runtime_module, "_backup_snapshot", racing_snapshot
    )

    result = status_run("run-race", runs_dir=tmp_path)

    assert triggered["done"]
    # Die Momentaufnahme ist entweder der Stand vor oder der Stand nach
    # dem nebenlaeufigen Schreibvorgang -- niemals eine unmoegliche
    # Mischung aus beiden.
    if result.status == "waiting_decision":
        assert result.round_id == waiting.round_id
        assert result.phase is waiting.phase
    else:
        assert result.status == "passed"
    runtime.close()


def _corrupt_latest_checkpoint(
    runtime: LoopRuntime, run_id: str, mutate
) -> None:
    """Schreibe einen neuen, gezielt beschaedigten Checkpoint fuer den
    Lauf, so wie ein realer, aber unvollstaendiger Schreibvorgang ihn
    hinterlassen koennte."""
    config = {"configurable": {"thread_id": run_id}}
    saver = runtime._checkpointer
    current = saver.get_tuple(config)
    checkpoint = dict(current.checkpoint)
    values = dict(checkpoint["channel_values"])
    mutate(values)
    checkpoint["channel_values"] = values
    # uuid6 statt uuid4: LangGraph waehlt den "neuesten" Checkpoint
    # ueber die sortierbare Checkpoint-ID; eine zufaellige uuid4 waere
    # nicht zuverlaessig groesser als die vorherige und liesse den
    # Test nichtdeterministisch fehlschlagen.
    checkpoint["id"] = str(uuid6())
    saver.put(current.config, checkpoint, current.metadata, {})


def test_status_reports_checkpoint_missing_required_field(tmp_path):
    runtime = LoopRuntime(
        RunStore(tmp_path, "run-missing-status"),
        FakeBuilder(),
        FakeReviewer([ReviewAction.NEEDS_DECISION]),
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    )
    runtime.start(_task("run-missing-status"), Limits())
    _corrupt_latest_checkpoint(
        runtime,
        "run-missing-status",
        lambda values: values.pop("status"),
    )
    runtime.close()
    _add_configuration(tmp_path, "run-missing-status")

    with pytest.raises(LoopResumeError):
        status_run("run-missing-status", runs_dir=tmp_path)


def test_status_reports_checkpoint_with_invalid_run_state(tmp_path):
    runtime = LoopRuntime(
        RunStore(tmp_path, "run-bad-run-state"),
        FakeBuilder(),
        FakeReviewer([ReviewAction.NEEDS_DECISION]),
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    )
    runtime.start(_task("run-bad-run-state"), Limits())

    def _break_run_state(values: dict) -> None:
        run_state = dict(values["run_state"])
        del run_state["schema_version"]
        values["run_state"] = run_state

    _corrupt_latest_checkpoint(
        runtime, "run-bad-run-state", _break_run_state
    )
    runtime.close()
    _add_configuration(tmp_path, "run-bad-run-state")

    with pytest.raises(LoopResumeError):
        status_run("run-bad-run-state", runs_dir=tmp_path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda values: values.__setitem__("status", "nonsense"),
        lambda values: values.__setitem__("round_id", -7),
        lambda values: values.__setitem__("round_id", True),
    ],
)
def test_status_rejects_semantically_invalid_required_fields(
    tmp_path, mutate
):
    """8to: ``status``/``round_id`` muessen echte, gueltige Werte sein,
    nicht nur irgendein vorhandenes JSON-Feld."""
    runtime = LoopRuntime(
        RunStore(tmp_path, "run-invalid-status"),
        FakeBuilder(),
        FakeReviewer([ReviewAction.NEEDS_DECISION]),
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    )
    runtime.start(_task("run-invalid-status"), Limits())
    _corrupt_latest_checkpoint(runtime, "run-invalid-status", mutate)
    runtime.close()
    _add_configuration(tmp_path, "run-invalid-status")

    with pytest.raises(LoopResumeError):
        status_run("run-invalid-status", runs_dir=tmp_path)


def test_status_cli_exits_with_code_2_for_incomplete_checkpoint(
    tmp_path,
):
    from typer.testing import CliRunner

    from ki_dev.cli import app

    runtime = LoopRuntime(
        RunStore(tmp_path, "run-cli-corrupt"),
        FakeBuilder(),
        FakeReviewer([ReviewAction.NEEDS_DECISION]),
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    )
    runtime.start(_task("run-cli-corrupt"), Limits())
    _corrupt_latest_checkpoint(
        runtime, "run-cli-corrupt", lambda values: values.pop("status")
    )
    runtime.close()
    _add_configuration(tmp_path, "run-cli-corrupt")

    result = CliRunner().invoke(
        app,
        [
            "loop",
            "status",
            "run-cli-corrupt",
            "--runs-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 2
    assert "run-cli-corrupt" in result.output


def _initialize_with_configuration(store: RunStore) -> None:
    store.initialize(
        {
            "schema_version": 1,
            "task": {},
            "limits": {},
            "configuration": {},
        }
    )


def test_status_reports_missing_checkpoint_clearly(tmp_path):
    store = RunStore(tmp_path, "run-no-checkpoint")
    _initialize_with_configuration(store)

    with pytest.raises(LoopResumeError):
        status_run("run-no-checkpoint", runs_dir=tmp_path)


def test_status_creates_no_checkpoint_file_for_incomplete_run(
    tmp_path,
):
    store = RunStore(tmp_path, "run-incomplete")
    _initialize_with_configuration(store)
    run_dir = tmp_path / "run-incomplete"
    before = _sidecar_free_snapshot(run_dir)
    assert "checkpoints.sqlite" not in before

    with pytest.raises(LoopResumeError):
        status_run("run-incomplete", runs_dir=tmp_path)

    after = _sidecar_free_snapshot(run_dir)
    assert after == before
    assert not store.checkpoint_path.exists()


def test_status_leaves_unusable_checkpoint_file_untouched(tmp_path):
    store = RunStore(tmp_path, "run-empty-checkpoint")
    _initialize_with_configuration(store)
    store.checkpoint_path.touch()
    before = store.checkpoint_path.read_bytes()

    with pytest.raises(LoopResumeError):
        status_run("run-empty-checkpoint", runs_dir=tmp_path)

    after = store.checkpoint_path.read_bytes()
    assert after == before


def test_status_leaves_complete_run_checkpoint_byte_identical(
    tmp_path,
):
    builder = FakeBuilder()
    reviewer = FakeReviewer(
        [ReviewAction.NEEDS_DECISION, ReviewAction.PASS]
    )
    with LoopRuntime(
        RunStore(tmp_path, "run-complete"),
        builder,
        reviewer,
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    ) as runtime:
        runtime.start(_task("run-complete"), Limits())

    _add_configuration(tmp_path, "run-complete")
    store = RunStore(tmp_path, "run-complete")
    checkpoint_before = store.checkpoint_path.read_bytes()
    run_dir = tmp_path / "run-complete"
    known_before = _sidecar_free_snapshot(run_dir)

    status_run("run-complete", runs_dir=tmp_path)
    status_run("run-complete", runs_dir=tmp_path)

    assert store.checkpoint_path.read_bytes() == checkpoint_before
    assert _sidecar_free_snapshot(run_dir) == known_before
