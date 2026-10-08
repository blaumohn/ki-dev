"""Charakterisierungsnetz für ``ki-dev step``: exakte Ausgaben.

Jede Variante vergleicht stdout, stderr und Exit-Code mit einer Datei
unter ``tests/golden/step/``. Zeitstempel, temporäre Pfade und der
Python-Pfad werden vor dem Vergleich ersetzt. Eine gewollte Änderung
wird mit ``UPDATE_GOLDEN=1`` neu geschrieben und im Diff begründet;
ohne den Schalter ist jede Abweichung ein Fehler.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ki_dev.cli import app
from tests import codex_session_fixtures as codex
from tests.fake_bd import FakeBd
from tests.fake_bd_command import BdScript
from tests.guideline_fixtures import write_guidelines
from tests.test_step_cli import FULL, _command, _preflight_project

GOLDEN = Path(__file__).parent / "golden" / "step"
runner = CliRunner()

REVIEW = ["step", "x-1", "--step", "review"]
NEXT = [*REVIEW, "--next-turn"]
FAIL = "import sys; sys.exit(1)"
SID = "0199aaaa-bbbb-cccc-dddd-eeeeffff0001"


def _decision(tmp_path: Path, **fields) -> str:
    value = {"event": "PASS", "detail": "", "requirement_ref": None}
    value.update(fields)
    path = tmp_path / "antwort.json"
    path.write_text(json.dumps(value))
    return str(path)


# (Name, Vorlauf-Prüfung oder None, Argumente; Pfade erst im Test)
CASES = [
    *(
        (f"step-{phase}", None, ["step", "x-1", "--step", phase])
        for phase in ("map", "graph", "materialize", "implement")
    ),
    *(
        (
            f"review-of-{phase}",
            None,
            [*REVIEW, "--review-of", phase],
        )
        for phase in ("map", "graph", "materialize")
    ),
    ("review-implement", "print(1)", REVIEW),
    ("next-turn-review", "print(1)", NEXT),
    ("next-turn-repair", FAIL, NEXT),
    (
        "next-turn-partial",
        "print(1)",
        [*NEXT, "--preflight-skip", "tests=nur Doku"],
    ),
    ("next-turn-of-map", None, [*NEXT, "--review-of", "map"]),
    ("decision-pass", None, "PASS"),
    ("decision-fix-bound", None, "fix-AC1"),
    ("decision-fix-unbound", None, "fix-AC9"),
    ("decision-source", None, "source"),
    ("decision-decision", None, "decision"),
]


@pytest.fixture
def bd(monkeypatch, tmp_path_factory):
    fake = BdScript(
        tmp_path_factory.mktemp("bd"),
        stdout=json.dumps([FULL]),
        stderr="",
    )
    fake.install(monkeypatch)
    return fake


@pytest.mark.parametrize(
    ("name", "check", "args"), CASES, ids=[c[0] for c in CASES]
)
def test_step_output_matches_golden(
    name, check, args, bd, tmp_path, monkeypatch
):
    if check is not None:
        _preflight_project(
            tmp_path, checks=f"[{_command('tests', check)}]"
        )
    write_guidelines(tmp_path)
    monkeypatch.chdir(tmp_path)
    if isinstance(args, str):
        args = [*NEXT, "--decision-file", _answer(tmp_path, args)]
    result = runner.invoke(app, args)
    _compare(name, result, tmp_path)


def _answer(tmp_path: Path, spec: str) -> str:
    if spec == "PASS":
        return _decision(tmp_path)
    if spec.startswith("fix-"):
        return _decision(
            tmp_path,
            event="fix",
            detail="Test fehlt",
            requirement_ref=spec.removeprefix("fix-"),
        )
    return _decision(tmp_path, event=spec, detail="Umfang?")


def test_local_matches_golden(tmp_path, monkeypatch):
    write_guidelines(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "")
    _compare("local", runner.invoke(app, ["step", "local"]), tmp_path)


def test_map_import_matches_golden(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    work = tmp_path / "work"
    sessions.mkdir()
    work.mkdir()
    write_guidelines(work)
    FakeBd(tmp_path, codex.SECRET).install(monkeypatch)
    monkeypatch.setenv("KI_DEV_CODEX_SESSIONS_DIR", str(sessions))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.chdir(work)
    rows = [codex.session_meta(SID), *codex.dialog(2)]
    codex.write_session(sessions, SID, rows, day="2026/09/17")
    result = runner.invoke(
        app,
        [
            "step",
            "map",
            "--agent",
            "codex",
            "--session",
            SID,
            "--title",
            "Test-Import",
        ],
    )
    _compare("map-import", result, tmp_path)


def _compare(name: str, result, tmp_path: Path) -> None:
    actual = _normalized(
        f"exit: {result.exit_code}\n"
        f"--- stdout ---\n{result.stdout}"
        f"--- stderr ---\n{result.stderr}",
        tmp_path,
    )
    path = GOLDEN / f"{name}.txt"
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
    assert path.exists(), f"{path.name} fehlt: UPDATE_GOLDEN=1 setzen"
    assert actual == path.read_text(encoding="utf-8")


def _normalized(text: str, tmp_path: Path) -> str:
    text = text.replace(str(tmp_path.resolve()), "<TMP>")
    text = text.replace(str(tmp_path), "<TMP>")
    text = text.replace(sys.executable, "<PY>")
    text = re.sub(r"vorlauf-start=\S+", "vorlauf-start=<ZEIT>", text)
    return re.sub(r"\d{8}T\d{6}\.\d+Z", "<STEMPEL>", text)
