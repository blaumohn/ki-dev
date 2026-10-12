"""Laufprofil als JSON Schema: Feldpfade ohne Werte, Rollenfelder je
Transport, Beispielprofil der Doku."""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path

import pytest

from ki_dev.flow_ops.implement.cli import load_profile
from ki_dev.flow_ops.implement.config import (
    RunConfigError,
    check_run_config,
)

DOC = Path(__file__).parent.parent / "docs" / "ausfuehrer.de.md"
SECRET = "geheim-4711"


def _profile(**changes):
    profile = {
        "workdir": "/work",
        "access_profile": "write",
        "worker": {
            "executor": "claude",
            "session_id": "w",
            "model": "m",
            "effort": "low",
        },
        "review": {"executor": "manual"},
        "finalization": {
            "target_workdir": "/ziel",
            "target_ref": "refs/heads/main",
            "commit_message": "Abschluss",
            "data_mode": "file_proposal",
        },
    }
    profile.update(changes)
    return profile


def test_valid_profile_passes():
    check_run_config(_profile(), "Profil")


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({SECRET: 1}, rf"\$: unbekannte Felder \['{SECRET}'\]"),
        (
            {"worker": {**_profile()["worker"], "timeout_s": SECRET}},
            r"worker\.timeout_s: type",
        ),
        ({"workdir": " "}, r"workdir: pattern"),
        (
            {"review": {"executor": "manual", "model": SECRET}},
            r"review: unbekannte Felder \['model'\]",
        ),
        (
            {"worker": {"executor": "claude"}},
            r"worker: fehlende Felder "
            r"\['session_id', 'model', 'effort'\]",
        ),
        (
            {"limits": {"changes_rounds": 1.5}},
            r"limits\.changes_rounds",
        ),
        ({"tests": [{"name": "t", "argv": []}]}, r"tests\.0\.argv"),
    ],
)
def test_errors_name_field_path_without_value(changes, message):
    with pytest.raises(RunConfigError, match=message) as caught:
        check_run_config(_profile(**changes), "Profil")

    if SECRET not in message:
        assert SECRET not in str(caught.value)


def test_documented_example_profile_passes(tmp_path):
    blocks = re.findall(r"```toml\n(.*?)```", DOC.read_text(), re.S)
    (example,) = [b for b in blocks if "access_profile" in b]
    path = tmp_path / "profil.toml"
    path.write_text(example, encoding="utf-8")

    profile = load_profile(path)

    assert profile.values == tomllib.loads(example)
    assert profile.ref() == {
        "path": str(path),
        "sha256": hashlib.sha256(example.encode()).hexdigest(),
    }
