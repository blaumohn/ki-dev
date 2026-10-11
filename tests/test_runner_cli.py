from __future__ import annotations

import json
from pathlib import Path

import pytest

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


def _tree(root: Path) -> dict[str, bytes]:
    """Dateibaum eines Laufverzeichnisses mit Inhalt."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
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


def _waiting_run(tmp_path: Path, run_id: str) -> RunRuntime:
    """Lauf bis zur wartenden Entscheidung; der Schreiber bleibt
    offen."""
    runtime = RunRuntime(
        RunStore(tmp_path, run_id),
        FakeWorker(),
        FakeReviewer(["decision", "PASS"]),
        StaticEvidenceCollector((_context(1),)),
        StaticFinalizer(),
    )
    runtime.start(_task(run_id), Limits())
    _add_configuration(tmp_path, run_id)
    return runtime


def test_status_reads_live_run_while_writer_is_open(tmp_path):
    runtime = _waiting_run(tmp_path, "run-live")
    try:
        result = status_run("run-live", runs_dir=tmp_path)
        assert result.status == "waiting_decision"
        assert result.phase is Phase.WAITING_DECISION
        assert result.round_id == 1
    finally:
        runtime.close()


def test_status_ignores_an_unfinished_replacement(tmp_path):
    """Ein abgebrochener Schreibvorgang hinterlässt höchstens eine
    temporäre Datei; gelesen wird der letzte ganze Stand."""
    _waiting_run(tmp_path, "run-crash").close()
    run_dir = tmp_path / "run-crash"
    (run_dir / ".record.json.abc.tmp").write_text("{halb")

    result = status_run("run-crash", runs_dir=tmp_path)

    assert result.status == "waiting_decision"


def _corrupt_record(tmp_path: Path, run_id: str, mutate) -> None:
    path = tmp_path / run_id / "record.json"
    document = json.loads(path.read_text())
    mutate(document)
    path.write_text(json.dumps(document))


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["data"].pop("round_id"),
        lambda d: d["data"]["run_state"].pop("schema_version"),
        lambda d: d["run"].__setitem__("state", ["nonsense"]),
        lambda d: d["data"].__setitem__("round_id", -7),
        lambda d: d["data"].__setitem__("round_id", True),
        lambda d: d.__setitem__("pending", {"id": "x"}),
    ],
)
def test_status_rejects_an_invalid_record(tmp_path, mutate):
    """8to: Pflichtfelder müssen echte, gültige Werte sein, nicht nur
    irgendein vorhandenes JSON-Feld."""
    _waiting_run(tmp_path, "run-invalid").close()
    _corrupt_record(tmp_path, "run-invalid", mutate)

    with pytest.raises(RunResumeError, match="unvollstaendig"):
        status_run("run-invalid", runs_dir=tmp_path)


def test_status_cli_exits_with_code_2_for_incomplete_record(
    tmp_path, capsys
):
    from ki_dev.cli import main

    _waiting_run(tmp_path, "run-cli-corrupt").close()
    _corrupt_record(
        tmp_path, "run-cli-corrupt", lambda d: d["data"].pop("round_id")
    )

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


def test_status_reports_missing_record_clearly(tmp_path):
    store = RunStore(tmp_path, "run-no-record")
    _initialize_with_configuration(store)

    with pytest.raises(RunResumeError, match="fehlt"):
        status_run("run-no-record", runs_dir=tmp_path)


def test_status_creates_no_file_for_incomplete_run(tmp_path):
    store = RunStore(tmp_path, "run-incomplete")
    _initialize_with_configuration(store)
    before = _tree(tmp_path)

    with pytest.raises(RunResumeError):
        status_run("run-incomplete", runs_dir=tmp_path)

    assert _tree(tmp_path) == before
    assert not store.record_path.exists()


def test_status_leaves_unusable_record_untouched(tmp_path):
    store = RunStore(tmp_path, "run-empty-record")
    _initialize_with_configuration(store)
    store.record_path.touch()

    with pytest.raises(RunResumeError):
        status_run("run-empty-record", runs_dir=tmp_path)

    assert store.record_path.read_bytes() == b""


def test_status_leaves_complete_run_byte_identical(tmp_path):
    _waiting_run(tmp_path, "run-complete").close()
    before = _tree(tmp_path / "run-complete")

    status_run("run-complete", runs_dir=tmp_path)
    status_run("run-complete", runs_dir=tmp_path)

    assert _tree(tmp_path / "run-complete") == before


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
