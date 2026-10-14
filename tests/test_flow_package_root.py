"""Ablaufpaket außerhalb des Gerüsts (ki-dev-ablauf-7p9): Vorlagen,
eigene Muster und ``ops = "./…"`` gelten relativ zur Ablaufdatei;
Gerüstteile nennt der Ablauf ausdrücklich (``ki_dev:review``), einen
Rückfall Paket → Gerüst gibt es nicht."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ki_dev.flow import model
from ki_dev.flow.model import FlowError, load_flow_file
from ki_dev.flow.package import import_ops
from ki_dev.runner.package import flow_digest
from tests.test_step_package import _FLOW

SHIPPED = Path(model.__file__).parent
OPS = """\
from .teil import WERT


def step_ops(flow):
    return (WERT, flow.name)
"""


def _package(root: Path, *, ops: str = "./paket") -> Path:
    """Testablauf aus test_step_package als Paket mit eigenen
    Vorlagen und eigenem Ops-Paket."""
    shutil.copytree(
        SHIPPED / "templates" / "review", root / "templates" / "review"
    )
    flow = root / "entwurf.toml"
    flow.write_text(
        _FLOW.replace(
            'ops = "tests.test_step_package"', f'ops = "{ops}"'
        ),
        encoding="utf-8",
    )
    (root / "paket").mkdir()
    (root / "paket" / "__init__.py").write_text(OPS, encoding="utf-8")
    (root / "paket" / "teil.py").write_text(
        f"WERT = {str(root)!r}\n", encoding="utf-8"
    )
    return flow


def test_templates_and_ops_load_relative_to_the_flow_file(tmp_path):
    flow = load_flow_file(_package(tmp_path))
    assert Path(str(flow.root)) == tmp_path
    module = import_ops(flow)
    assert Path(module.__file__).parent == tmp_path / "paket"
    assert module.step_ops(flow) == (str(tmp_path), "entwurf")


def test_missing_template_is_an_error_not_a_fallback(tmp_path):
    flow = _package(tmp_path)
    (tmp_path / "templates" / "review" / "local.txt").unlink()
    with pytest.raises(FlowError, match="review/local.txt fehlt"):
        load_flow_file(flow)


def test_missing_ops_is_an_error(tmp_path):
    flow = load_flow_file(_package(tmp_path, ops="./fehlt"))
    with pytest.raises(FlowError, match="nicht ladbar"):
        import_ops(flow)


def test_two_places_load_their_own_ops_and_share_the_digest(
    tmp_path,
):
    one = load_flow_file(_package(tmp_path / "eins"))
    two = load_flow_file(_package(tmp_path / "zwei"))
    assert import_ops(one).step_ops(one)[0] == str(tmp_path / "eins")
    assert import_ops(two).step_ops(two)[0] == str(tmp_path / "zwei")
    assert flow_digest(one) == flow_digest(two)


def test_local_pattern_catalog_is_read_from_the_package(tmp_path):
    shutil.copytree(
        SHIPPED / "templates" / "review",
        tmp_path / "templates" / "review",
    )
    (tmp_path / "muster").mkdir()
    shutil.copy(
        SHIPPED / "patterns" / "review.toml",
        tmp_path / "muster" / "meins.toml",
    )
    flow = tmp_path / "map.toml"
    flow.write_text(
        (SHIPPED / "map.toml")
        .read_text(encoding="utf-8")
        .replace('["ki_dev:review"]', '["./muster/meins"]'),
        encoding="utf-8",
    )
    assert load_flow_file(flow).name == "map"
    (tmp_path / "muster" / "meins.toml").unlink()
    with pytest.raises(FlowError, match="muster/meins fehlt"):
        load_flow_file(flow)
