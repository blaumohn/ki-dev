"""Echter Demo-Lauf trotz älterem Paket im geerbten Python-Suchpfad."""

import json
import shutil
from pathlib import Path

import pytest
from plumbum import local

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(shutil.which("bd") is None, reason="bd fehlt")
def test_demo_uses_checkout_for_run_and_history(tmp_path):
    old = tmp_path / "old installation"
    package = old / "ki_dev"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "raise RuntimeError('Altes installiertes Paket geladen')\n"
    )
    (old / "implement.toml").write_text("Ungültiges altes Ablaufpaket")
    demo = tmp_path / "demo"
    with local.cwd(ROOT), local.env(
        PYTHONPATH=str(old), KI_DEV_FLOW_PATH=str(old),
    ):
        code, output, error = local["bash"].run(
            args=[str(ROOT / "scripts/demo-mock-lauf.sh"), str(demo)],
            retcode=None,
            timeout=120,
        )
    assert code == 0, error[-3000:]
    result = json.loads((demo / "result.json").read_text())
    assert (result["status"], result["round_id"]) == ("passed", 2)
    assert "Runde 1  Review    fix" in output
    assert "Runde 2  Review    PASS" in output
    assert "Laufverzeichnis:" in output
    with local.cwd(demo / "ziel"):
        committed = local["git"].run(
            args=["show", "main:MOCK.md"], retcode=0, timeout=10,
        )[1]
    assert committed == "Runde 1\nRunde 2\n"
