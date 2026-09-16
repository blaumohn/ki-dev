from __future__ import annotations

from pathlib import Path

import pytest
from plumbum import CommandNotFound, local

from ki_dev.deltas import (
    BD_DIFF_INTERFACE,
    SUPPORTED_BD_VERSION,
    ChangeMedium,
    DeltaCommandError,
    RefBoundary,
    VcsRef,
    build_beads_delta,
    capture_beads_ref,
    installed_bd_version,
    run_command,
    verify_bd_version,
)

from .conftest import run_bd


def _bd_available() -> bool:
    try:
        local["bd"]
    except CommandNotFound:
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _bd_available(), reason="bd lokal nicht installiert"
)


def _delta(repo: Path, base: VcsRef, result: VcsRef):
    return build_beads_delta(repo, RefBoundary(base, result))


def _available_commands(help_text: str) -> set[str]:
    body = help_text.partition("Available Commands:")[2]
    section = body.split("\n\n", 1)[0]
    return {
        line.split()[0] for line in section.splitlines() if line.strip()
    }


def test_supported_version_is_pinned():
    assert SUPPORTED_BD_VERSION == "1.2.2"
    assert BD_DIFF_INTERFACE == ("bd", "diff", "FROM_REF", "TO_REF")


def test_installed_bd_matches_pinned_version():
    assert installed_bd_version() == SUPPORTED_BD_VERSION
    verify_bd_version()


def test_bd_diff_interface_matches_reality():
    diff_help = run_command(["bd", "diff", "--help"]).require_success()
    assert "bd diff <from-ref> <to-ref>" in diff_help

    vc_help = run_command(["bd", "vc", "--help"]).require_success()
    commands = _available_commands(vc_help)
    assert "diff" not in commands
    assert {"commit", "status"} <= commands


def test_capture_beads_ref_reads_dolt_commit(work_repo: Path):
    ref = capture_beads_ref(work_repo)
    assert ref.medium is ChangeMedium.BEADS
    assert ref.value
    assert capture_beads_ref(work_repo) == ref


def test_beads_delta_reports_issue_changes(work_repo: Path):
    base = capture_beads_ref(work_repo)
    issue_id = run_bd(work_repo, "q", "Erste bd-Aufgabe").strip()
    after_create = capture_beads_ref(work_repo)

    created = _delta(work_repo, base, after_create)
    assert not created.is_empty
    assert [c.issue_id for c in created.issues] == [issue_id]
    assert created.issues[0].change_type == "added"
    assert issue_id in created.summary

    run_bd(work_repo, "update", issue_id, "--status", "in_progress")
    after_update = capture_beads_ref(work_repo)
    changed = _delta(work_repo, after_create, after_update)
    assert [c.change_type for c in changed.issues] == ["modified"]


def test_beads_delta_empty_for_same_ref(work_repo: Path):
    ref = capture_beads_ref(work_repo)
    delta = _delta(work_repo, ref, ref)
    assert delta.is_empty
    assert delta.issues == ()


def test_beads_delta_errors_on_unknown_ref(work_repo: Path):
    ref = capture_beads_ref(work_repo)
    bogus = VcsRef(ChangeMedium.BEADS, "deadbeefdeadbeef")
    with pytest.raises(DeltaCommandError):
        _delta(work_repo, bogus, ref)
