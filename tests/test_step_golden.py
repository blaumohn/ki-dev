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
from ki_dev.ops.checks import preflight
from tests import codex_session_fixtures as codex
from tests.fake_bd import FakeBd
from tests.fake_bd_command import BdScript
from tests.guideline_fixtures import write_guidelines
from tests.test_step_cli import FULL, _command, _preflight_project
from tests.turn_helpers import flow_step

GOLDEN = Path(__file__).parent / "golden" / "step"
runner = CliRunner()

FAIL = "import sys; sys.exit(1)"
SID = "0199aaaa-bbbb-cccc-dddd-eeeeffff0001"
DONE = ("{}", None)
PREFLIGHT = {
    "event": "checks_passed",
    "facts": ["full_checks"],
    "report": None,
    "finding": None,
}


def _verdict(event: str, ref: str | None = None) -> str:
    detail = {"PASS": "", "fix": "Test fehlt"}.get(event, "Umfang?")
    return json.dumps(
        {"event": event, "detail": detail, "requirement_ref": ref}
    )


# (Name, Vorlauf-Prüfung oder None, Ablauf, Argumente nach x-1,
# Antwortdateien: Name → Inhalt)
CASES = [
    *(
        (f"step-{phase}", None, phase, [phase], {})
        for phase in ("map", "graph", "materialize")
    ),
    ("step-implement", None, "implement_review", ["implement"], {}),
    *(
        (f"{phase}-review", None, phase, [f"{phase}.review"], {})
        for phase in ("map", "graph", "materialize")
    ),
    (
        "implement-written",
        "print(1)",
        "implement_review",
        ["implement", "implement=done.json"],
        {"done.json": "{}"},
    ),
    (
        "implement-corrected",
        "print(1)",
        "implement_review",
        ["implement.correction", "implement.correction=done.json"],
        {"done.json": '{"feedback": "Test ergänzt"}'},
    ),
    (
        "implement-corrected-red",
        FAIL,
        "implement_review",
        ["implement.correction", "implement.correction=done.json"],
        {"done.json": "{}"},
    ),
    (
        "implement-corrected-partial",
        "print(1)",
        "implement_review",
        [
            "implement.correction",
            "implement.correction=done.json",
            "--preflight-skip",
            "tests=nur Doku",
        ],
        {"done.json": "{}"},
    ),
    (
        "map-corrected",
        None,
        "map",
        ["map.correction", "map.correction=done.json"],
        {"done.json": "{}"},
    ),
    (
        "map-review-fix",
        None,
        "map",
        ["map.review", "map.review=review.json"],
        {"review.json": _verdict("fix", "AC1")},
    ),
    (
        "map-review-pass",
        None,
        "map",
        ["map.review", "map.review=review.json"],
        {"review.json": _verdict("PASS")},
    ),
    *(
        (
            f"implement-review-{name}",
            None,
            "implement_review",
            [
                "implement.review",
                "implement.review=review.json",
                "implement.preflight=vorlauf.json",
            ],
            {
                "review.json": verdict,
                "vorlauf.json": json.dumps(PREFLIGHT),
            },
        )
        for name, verdict in (
            ("pass", _verdict("PASS")),
            ("fix-bound", _verdict("fix", "AC1")),
            ("fix-unbound", _verdict("fix", "AC9")),
            ("source", _verdict("source")),
            ("decision", _verdict("decision")),
        )
    ),
    (
        "implement-review-pass-without-preflight",
        None,
        "implement_review",
        ["implement.review", "implement.review=review.json"],
        {"review.json": _verdict("PASS")},
    ),
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
    ("name", "check", "flow", "args", "files"),
    CASES,
    ids=[c[0] for c in CASES],
)
def test_step_output_matches_golden(
    name, check, flow, args, files, bd, tmp_path, monkeypatch
):
    if check is not None:
        # Die argv-Kürzung hinge sonst vom Pfad des venv ab;
        # geprüft ist sie in test_step_preflight.py.
        monkeypatch.setattr(
            preflight, "_MAX_ARGV_DISPLAY_CHARS", 10_000
        )
        _preflight_project(
            tmp_path, checks=f"[{_command('tests', check)}]"
        )
    write_guidelines(tmp_path)
    for file, content in files.items():
        (tmp_path / file).write_text(content, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    _compare(name, flow_step(flow, "x-1", *args), tmp_path)


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
