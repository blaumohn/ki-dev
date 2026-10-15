"""Ohne --spec bleiben Anforderungstests aus make test und
make readme-check heraus (tests/spec/plugin.py)."""

from __future__ import annotations

import pytest

from tests.spec.inner import run_inner

SAMPLES = """
import pytest

@pytest.mark.requirement("DEMO-RED")
def test_red():
    raise AssertionError("rot erlaubt")

@pytest.mark.control(target="scaffold", expect="passed")
def test_control():
    raise AssertionError("nur mit --spec")

def test_plain():
    pass
"""


@pytest.mark.parametrize("args", [(), ("-m", "not docker")])
def test_spec_items_deselected_without_option(tmp_path, args):
    run = run_inner(
        tmp_path,
        {"catalog.toml": "[requirement]\n", "test_samples.py": SAMPLES},
        *args,
    )
    assert run.code == pytest.ExitCode.OK, run.output
    assert "1 passed, 2 deselected" in run.output
    assert run.report is None
