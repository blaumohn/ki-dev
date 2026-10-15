"""Innerer pytest-Lauf mit dem Spec-Plugin für Gerüstkontrollen.

Die Kontrollen prüfen den Testprüfer an bekannten Beispielen in einem
eigenen Prozess und Verzeichnis, damit ihr Bericht den äußeren Lauf
nicht berührt.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

from plumbum import local

ROOT = Path(__file__).resolve().parents[2]
INI = "[pytest]\nspec_catalog = catalog.toml\n"


@dataclass(frozen=True)
class InnerRun:
    code: int
    output: str
    report: dict | None

    def row(self, rid: str) -> dict:
        rows = {row["id"]: row for row in self.report["requirements"]}
        return rows[rid]


def run_inner(work: Path, files: dict[str, str], *args) -> InnerRun:
    for name, text in {"pytest.ini": INI, **files}.items():
        (work / name).write_text(textwrap.dedent(text))
    pythonpath = os.pathsep.join([str(ROOT), str(ROOT / "src")])
    with local.env(PYTHONPATH=pythonpath):
        code, out, err = local[sys.executable].run(
            args=[
                "-m", "pytest", "-q",
                "-p", "tests.spec.plugin",
                "-p", "no:cacheprovider",
                "--spec-report", "report",
                *args,
            ],
            cwd=work,
            retcode=None,
            timeout=180,
        )
    path = work / "report" / "report.json"
    report = json.loads(path.read_text()) if path.exists() else None
    return InnerRun(code, out + err, report)
