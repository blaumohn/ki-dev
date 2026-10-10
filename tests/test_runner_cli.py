from __future__ import annotations

import json
from pathlib import Path

import pytest
from langgraph.checkpoint.base import uuid6

from ki_dev.adapter.contract import (
    RunTask,
)
from ki_dev.repository_finalization import StaticFinalizer
from ki_dev.run_store import RunStore, RunStoreError
from ki_dev.runner.cli import RunConfigError, status_run
from ki_dev.runner.machine import Limits, Phase
from ki_dev.runner.run_config import check_run_config
from ki_dev.runner.runtime import (
    RunResumeError,
    RunRuntime,
    StaticEvidenceCollector,
)
from tests.test_runner_runtime import (
    FakeReviewer,
    FakeWorker,
    _context,
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
    worker = FakeWorker()
    reviewer = FakeReviewer(
        ["decision", "PASS"]
    )
    with RunRuntime(
        RunStore(tmp_path, "run-status"),
        worker,
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
    assert worker.calls == 1
    assert reviewer.calls == 1


def test_status_works_with_relative_runs_dir(tmp_path, monkeypatch):
    """0we: der CLI-Standard ``--runs-dir .ki-dev/runs`` ist relativ;
    ``as_uri()`` braucht aber einen absoluten Pfad."""
    worker = FakeWorker()
    reviewer = FakeReviewer(["decision"])
    monkeypatch.chdir(tmp_path)
    relative_runs_dir = Path(".ki-dev/runs")
    with RunRuntime(
        RunStore(relative_runs_dir, "run-relative"),
        worker,
        reviewer,
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    ) as runtime:
        waiting = runtime.start(_task("run-relative"), Limits())
    _add_configuration(relative_runs_dir, "run-relative")

    result = status_run("run-relative", runs_dir=relative_runs_dir)

    assert result.status == "waiting_decision"
    assert result.round_id == waiting.round_id


def test_status_reports_missing_run_clearly(tmp_path):
    with pytest.raises(RunStoreError):
        status_run("does-not-exist", runs_dir=tmp_path)


def test_status_reports_manifest_without_configuration(tmp_path):
    with RunRuntime(
        RunStore(tmp_path, "run-no-config"),
        FakeWorker(),
        FakeReviewer(["PASS"]),
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    ) as runtime:
        runtime.start(_task("run-no-config"), Limits())

    with pytest.raises(RunConfigError):
        status_run("run-no-config", runs_dir=tmp_path)


def test_status_reads_live_run_while_writer_holds_wal_open(
    tmp_path,
):
    worker = FakeWorker()
    reviewer = FakeReviewer(
        ["decision", "PASS"]
    )
    runtime = RunRuntime(
        RunStore(tmp_path, "run-live"),
        worker,
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
        assert worker.calls == 1
        assert reviewer.calls == 1
    finally:
        runtime.close()


def test_status_reads_crash_state_with_wal_but_no_shm(tmp_path):
    worker = FakeWorker()
    reviewer = FakeReviewer(
        ["decision", "PASS"]
    )
    runtime = RunRuntime(
        RunStore(tmp_path, "run-crash"),
        worker,
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
    # zurueckbleiben. Ein sauberes runtime.close() raeumt je nach
    # SQLite-Build beides auf oder behaelt beides (dauerhaftes WAL,
    # macOS-Host); daher wird der Zustand hier gezielt aus den waehrend
    # des offenen Laufs erfassten Bytes rekonstruiert.
    (run_dir / "checkpoints.sqlite").write_bytes(main_bytes)
    (run_dir / "checkpoints.sqlite-wal").write_bytes(wal_bytes)
    (run_dir / "checkpoints.sqlite-shm").unlink(missing_ok=True)

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
    import ki_dev.runner.runtime as run_runtime_module

    worker = FakeWorker()
    reviewer = FakeReviewer(
        ["decision", "PASS"]
    )
    runtime = RunRuntime(
        RunStore(tmp_path, "run-race"),
        worker,
        reviewer,
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    )
    waiting = runtime.start(_task("run-race"), Limits())
    _add_configuration(tmp_path, "run-race")

    triggered = {"done": False}

    def racing_snapshot(source, destination):
        target = run_runtime_module.sqlite3.connect(destination)

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
        run_runtime_module, "_backup_snapshot", racing_snapshot
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
    runtime: RunRuntime, run_id: str, mutate
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
    runtime = RunRuntime(
        RunStore(tmp_path, "run-missing-status"),
        FakeWorker(),
        FakeReviewer(["decision"]),
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

    with pytest.raises(RunResumeError):
        status_run("run-missing-status", runs_dir=tmp_path)


def test_status_reports_checkpoint_with_invalid_run_state(tmp_path):
    runtime = RunRuntime(
        RunStore(tmp_path, "run-bad-run-state"),
        FakeWorker(),
        FakeReviewer(["decision"]),
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

    with pytest.raises(RunResumeError):
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
    runtime = RunRuntime(
        RunStore(tmp_path, "run-invalid-status"),
        FakeWorker(),
        FakeReviewer(["decision"]),
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    )
    runtime.start(_task("run-invalid-status"), Limits())
    _corrupt_latest_checkpoint(runtime, "run-invalid-status", mutate)
    runtime.close()
    _add_configuration(tmp_path, "run-invalid-status")

    with pytest.raises(RunResumeError):
        status_run("run-invalid-status", runs_dir=tmp_path)


def test_status_cli_exits_with_code_2_for_incomplete_checkpoint(
    tmp_path, capsys
):
    from ki_dev.cli import main

    runtime = RunRuntime(
        RunStore(tmp_path, "run-cli-corrupt"),
        FakeWorker(),
        FakeReviewer(["decision"]),
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    )
    runtime.start(_task("run-cli-corrupt"), Limits())
    _corrupt_latest_checkpoint(
        runtime, "run-cli-corrupt", lambda values: values.pop("status")
    )
    runtime.close()
    _add_configuration(tmp_path, "run-cli-corrupt")

    with pytest.raises(SystemExit) as raised:
        main(
            [
                "-f",
                "implement",
                "status",
                "run-cli-corrupt",
                "--runs-dir",
                str(tmp_path),
            ]
        )

    assert raised.value.code == 2
    assert "run-cli-corrupt" in capsys.readouterr().err


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

    with pytest.raises(RunResumeError):
        status_run("run-no-checkpoint", runs_dir=tmp_path)


def test_status_creates_no_checkpoint_file_for_incomplete_run(
    tmp_path,
):
    store = RunStore(tmp_path, "run-incomplete")
    _initialize_with_configuration(store)
    run_dir = tmp_path / "run-incomplete"
    before = _sidecar_free_snapshot(run_dir)
    assert "checkpoints.sqlite" not in before

    with pytest.raises(RunResumeError):
        status_run("run-incomplete", runs_dir=tmp_path)

    after = _sidecar_free_snapshot(run_dir)
    assert after == before
    assert not store.checkpoint_path.exists()


def test_status_leaves_unusable_checkpoint_file_untouched(tmp_path):
    store = RunStore(tmp_path, "run-empty-checkpoint")
    _initialize_with_configuration(store)
    store.checkpoint_path.touch()
    before = store.checkpoint_path.read_bytes()

    with pytest.raises(RunResumeError):
        status_run("run-empty-checkpoint", runs_dir=tmp_path)

    after = store.checkpoint_path.read_bytes()
    assert after == before


def test_status_leaves_complete_run_checkpoint_byte_identical(
    tmp_path,
):
    worker = FakeWorker()
    reviewer = FakeReviewer(
        ["decision", "PASS"]
    )
    with RunRuntime(
        RunStore(tmp_path, "run-complete"),
        worker,
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


def test_configured_manual_relay_round_trip(monkeypatch, tmp_path):
    """Adapter manual über die echte Konfiguration: Start hält
    mit ``awaiting_input``, der Bote legt die Antwort ab, ``resume``
    fährt dieselbe Operation weiter bis ``passed``."""
    from ki_dev.runner import cli as runner_cli

    monkeypatch.setattr(
        runner_cli,
        "RepositoryEvidenceCollector",
        lambda **_: StaticEvidenceCollector((_context(1),)),
    )
    monkeypatch.setattr(
        runner_cli, "_finalizer", lambda _: StaticFinalizer()
    )
    config = {
        "task": "Auftrag",
        "acceptance_criteria": ["Kriterium 1"],
        "sources": [],
        "workdir": str(tmp_path),
        "access_profile": "write",
"finalization": {
            "target_workdir": str(tmp_path),
            "target_ref": "refs/heads/main",
            "commit_message": "Abschluss",
            "data_mode": "file_proposal",
        },
        "worker": {"executor": "inbox"},
        "review": {"executor": "mock", "answers": ["PASS"]},
        "tests": [],
    }
    runs = tmp_path / "runs"
    halted = runner_cli.start_run(config, run_id="r-1", runs_dir=runs)
    assert (halted.status, halted.phase) == (
        "awaiting_input",
        Phase.WORKER_STEP,
    )
    assert status_run("r-1", runs_dir=runs).status == "awaiting_input"
    (ask,) = (runs / "r-1" / "inbox").glob("*.input.md")
    ask.with_name(ask.name.replace(".input.", ".answer.")).write_text(
        "Gebaut."
    )
    result = runner_cli.resume_run("r-1", runs_dir=runs, answer=None)
    assert result.status == "passed"


def test_resume_override_replaces_role_only_for_this_call(
    monkeypatch, tmp_path
):
    """``resume --adapter worker=mock``: die Rolle läuft mit dem Ersatz,
    die Kante nennt ihn; das Manifest behält die Profilrolle."""
    from ki_dev.runner import cli as runner_cli

    monkeypatch.setattr(
        runner_cli,
        "RepositoryEvidenceCollector",
        lambda **_: StaticEvidenceCollector((_context(1),)),
    )
    monkeypatch.setattr(
        runner_cli, "_finalizer", lambda _: StaticFinalizer()
    )
    config = {
        "task": "Auftrag",
        "acceptance_criteria": ["Kriterium 1"],
        "sources": [],
        "workdir": str(tmp_path),
        "access_profile": "write",
"finalization": {
            "target_workdir": str(tmp_path),
            "target_ref": "refs/heads/main",
            "commit_message": "Abschluss",
            "data_mode": "file_proposal",
        },
        "worker": {"executor": "inbox"},
        "review": {"executor": "mock", "answers": ["PASS"]},
        "tests": [],
    }
    runs = tmp_path / "runs"
    halted = runner_cli.start_run(config, run_id="r-1", runs_dir=runs)
    assert halted.status == "awaiting_input"

    result = runner_cli.resume_run(
        "r-1",
        runs_dir=runs,
        answer=None,
        overrides=runner_cli.adapter_overrides(["worker=mock"]),
    )

    assert result.status == "passed"
    assert (tmp_path / "MOCK.md").read_text() == "Runde 1\n"
    store = RunStore(runs, "r-1")
    manifest = store.load_manifest()["configuration"]
    assert manifest["worker"] == {"executor": "inbox"}
    records = [
        json.loads(line)
        for line in (store.run_dir / "events.jsonl")
        .read_text()
        .splitlines()
    ]
    worker = [r for r in records if r["state"] == "worker_step"]
    assert [r["adapter"] for r in worker] == ["mock"]


def test_manifest_and_status_name_the_profile(monkeypatch, tmp_path):
    from ki_dev.runner import cli as runner_cli

    monkeypatch.setattr(
        runner_cli,
        "RepositoryEvidenceCollector",
        lambda **_: StaticEvidenceCollector((_context(1),)),
    )
    monkeypatch.setattr(
        runner_cli, "_finalizer", lambda _: StaticFinalizer()
    )
    path = tmp_path / "profil.toml"
    path.write_text(
        f'workdir = "{tmp_path}"\n'
        'access_profile = "write"\n'
        "[worker]\nexecutor = \"mock\"\n"
        "[review]\nexecutor = \"mock\"\n"
        "[finalization]\n"
        f'target_workdir = "{tmp_path}"\n'
        'target_ref = "refs/heads/main"\n'
        'commit_message = "c"\n'
        'data_mode = "file_proposal"\n',
        encoding="utf-8",
    )
    profile = runner_cli.load_profile(path)
    config = {
        **profile.values,
        "task": "Auftrag",
        "acceptance_criteria": ["Kriterium 1"],
    }
    runs = tmp_path / "runs"

    runner_cli.start_run(
        config, run_id="r-p", runs_dir=runs, profile=profile
    )

    expected = {"path": str(path), "sha256": profile.sha256}
    manifest = RunStore(runs, "r-p").load_manifest()
    assert manifest["profile"] == expected
    document = runner_cli.status_document("r-p", runs_dir=runs)
    assert document["profile"] == expected
    assert document["status"] == "passed"


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (["claude"], "nur inbox, manual, mock"),
        (["planner=manual"], "Rolle worker, review"),
    ],
)
def test_adapter_overrides_are_checked(values, message):
    from ki_dev.runner import cli as runner_cli

    with pytest.raises(RunConfigError, match=message):
        runner_cli.adapter_overrides(values)


def test_unknown_mock_answer_is_rejected():
    with pytest.raises(
        RunConfigError, match=r"review\.answers\.0: enum"
    ):
        check_run_config(
            {
                "workdir": "/w",
                "access_profile": "write",
                "worker": {"executor": "mock"},
                "review": {"executor": "mock", "answers": ["OK"]},
                "finalization": {
                    "target_workdir": "/z",
                    "target_ref": "refs/heads/main",
                    "commit_message": "c",
                    "data_mode": "file_proposal",
                },
            },
            "Profil",
        )
