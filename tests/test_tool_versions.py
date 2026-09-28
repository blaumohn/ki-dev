"""Vertrag und Build-Ausgabe der gemeinsamen Versionsquelle."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from plumbum import local

from ki_dev import tool_versions


def test_build_arguments_cover_dockerfile_pins():
    root = Path(__file__).resolve().parents[1]
    with local.cwd(root):
        output = (
            local[sys.executable]
            .run(
                args=["-m", "ki_dev.tool_versions"],
                retcode=0,
                timeout=10,
            )[1]
            .splitlines()
        )
    assert output[::2] == ["--build-arg"] * (len(output) // 2)
    arguments = dict(line.split("=", 1) for line in output[1::2])
    assert arguments == tool_versions.load_tool_versions()
    dockerfile = (root / "docker/agent/Dockerfile").read_text()
    for key in arguments:
        assert f"ARG {key}\n" in dockerfile
        assert f"${{{key}}}" in dockerfile
    assert (
        "-m ki_dev.tool_versions"
        in (root / "scripts/agent-container").read_text()
    )


@pytest.mark.parametrize(
    "mutation", ["missing", "unknown", "type", "empty"]
)
def test_invalid_manifest_fails(mutation):
    values = tool_versions.load_tool_versions()
    if mutation == "missing":
        del values["CODEX_VERSION"]
    elif mutation == "unknown":
        values["SECRET_EXTRA"] = "sensitive-value"
    elif mutation == "type":
        values["CODEX_VERSION"] = 123
    else:
        values["CODEX_VERSION"] = ""
    with pytest.raises(ValueError) as error:
        tool_versions.validate_tool_versions(values)
    assert "sensitive-value" not in str(error.value)
    assert "SECRET_EXTRA" not in str(error.value)


@pytest.mark.parametrize("content", [None, "{", json.dumps([])])
def test_missing_or_invalid_resource_fails(
    tmp_path, monkeypatch, content
):
    monkeypatch.setattr(tool_versions, "files", lambda _: tmp_path)
    if content is not None:
        (tmp_path / "tool-versions.json").write_text(content)
    with pytest.raises((FileNotFoundError, ValueError)):
        tool_versions.load_tool_versions()
