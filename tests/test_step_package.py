"""step zustandslos und ablaufneutral (ki-dev-ablauf-ige.9): ein
Testablauf ohne Review-Muster mit drei Rollen läuft mit
``ki-dev -f ABLAUF step``; was Antworten bedeuten, sagen die Ops
seines Pakets (dieses Modul), was eine Übergabe von weiter vorn
braucht, deklariert der Ablauf."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import ClassVar

import pytest
from typer.testing import CliRunner

from ki_dev.cli import main
from ki_dev.flow.model import FlowError, load_flow_file
from ki_dev.flow.templates import text
from ki_dev.ops.context.bead_input import BeadInput
from ki_dev.runner.limits import EMPTY_FLOW_SCHEMA
from ki_dev.runner.protocol import RunModel
from ki_dev.step import projection
from ki_dev.step.cli import step_app
from ki_dev.step.package import AnswerError, load_package_ops

runner = CliRunner()

# Drei Rollen: work schreibt einen Bericht, summary fasst ihn
# zusammen (braucht report aus work), check prüft.
_FLOW = """
name = "entwurf"
start = "work"
final = ["finished"]
templates = "review"
ops = "tests.test_step_package"

[vocabulary]
kinds = ["work", "final"]
events = ["ready"]
operations = ["turn"]

[[state]]
id = "work"
kind = "work"
operation = [{ do = "turn", template = "local", role = "worker" }]

[[state]]
id = "summary"
kind = "work"

[[state.operation]]
do = "turn"
template = "role-map"
role = "writer"
input = { report = "work" }

[[state]]
id = "check"
kind = "work"
operation = [{ do = "turn", template = "role-graph", role = "checker" }]

[[state]]
id = "finished"
kind = "final"

[[transition]]
source = "work"
event = "ready"
target = "summary"

[[transition]]
source = "summary"
event = "ready"
target = "check"

[[transition]]
source = "check"
event = "ready"
target = "finished"
"""


@dataclass
class DraftOps:
    """Ops des Testpakets: jede Antwort ist ein JSON-Objekt, seine
    Felder werden Laufdaten, das Ereignis heißt ``ready``."""

    model: type[RunModel] = RunModel
    flow_limits: ClassVar[dict] = {}
    flow_limits_schema: ClassVar[dict] = EMPTY_FLOW_SCHEMA

    def catalog(self, _call):
        return {}

    def read(self, _call, handoff, raw):
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise AnswerError(
                f"Antwort in {handoff.state}: kein Objekt"
            )
        return value, "ready"

    def subject(self, base, _data, _path):
        return base

    def review(self, _state):
        return False


def package_ops(_flow):
    return DraftOps()


@pytest.fixture
def flow_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    issue = BeadInput(id="x-1", title="Titel", description="D")
    monkeypatch.setattr(projection, "read_issue", lambda *_: issue)
    path = tmp_path / "entwurf.toml"
    path.write_text(_FLOW, encoding="utf-8")
    # Vorlagen liegen neben der Ablaufdatei, nicht im Gerüst.
    templates = tmp_path / "templates" / "review"
    templates.mkdir(parents=True)
    for name in ("local", "role-map", "role-graph"):
        (templates / f"{name}.txt").write_text(
            text("review", name), encoding="utf-8"
        )
    (tmp_path / "work.json").write_text('{"report": "R"}')
    (tmp_path / "summary.json").write_text("{}")
    (tmp_path / "check.json").write_text("{}")
    return path


def _step(path, *args):
    app = step_app(load_flow_file(path), path)
    return runner.invoke(app, list(args))


def test_without_answer_prints_the_handoff_of_the_state(flow_file):
    result = _step(flow_file, "x-1", "work")
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("Schritt: local")


def test_answer_takes_the_edge_and_prints_the_next_handoff(flow_file):
    result = _step(flow_file, "x-1", "work", "work=work.json")
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("Schritt: map")


def test_missing_declared_input_names_name_and_origin(flow_file):
    result = _step(flow_file, "x-1", "summary")
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "summary braucht report (aus work" in result.stderr
    assert "work=DATEI.json" in result.stderr


def test_earlier_answer_supplies_the_declared_input(flow_file):
    alone = _step(flow_file, "x-1", "summary", "work=work.json")
    assert alone.exit_code == 0, alone.output
    assert alone.stdout.startswith("Schritt: map")
    answered = _step(
        flow_file,
        "x-1",
        "summary",
        "summary=summary.json",
        "work=work.json",
    )
    assert answered.exit_code == 0, answered.output
    assert answered.stdout.startswith("Schritt: graph")


def test_answer_needs_no_input_of_its_own_handoff(flow_file):
    """Die Eingabe gilt für die Übergabe von summary, nicht für ihre
    Antwort: die gab ein früherer Aufruf aus."""
    result = _step(flow_file, "x-1", "summary", "summary=summary.json")
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("Schritt: graph")


def test_last_answer_ends_the_flow(flow_file):
    result = _step(flow_file, "x-1", "check", "check=check.json")
    assert result.exit_code == 0, result.output
    assert result.stdout == "Ende: finished (keine weitere Übergabe)\n"


def test_same_input_gives_same_output_and_nothing_is_stored(
    flow_file, tmp_path
):
    before = sorted(p.name for p in tmp_path.iterdir())
    args = ("x-1", "summary", "work=work.json")
    first = _step(flow_file, *args)
    assert _step(flow_file, *args).stdout == first.stdout
    assert sorted(p.name for p in tmp_path.iterdir()) == before


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("x-1", "finished"), "finished hat keine Übergabe"),
        (("x-1", "nix"), "nix ist kein Zustand"),
        (("x-1", "work", "work"), "erwartet ZUSTAND=DATEI"),
        (("x-1", "work", "nix=a.json"), "nix: kein Zustand"),
        (("x-1", "work", "finished=a.json"), "antwortet nie"),
        (
            ("x-1", "work", "work=work.json", "work=work.json"),
            "doppelt",
        ),
        (("x-1", "work", "work=-", "check=-"), "stdin (-)"),
        (("x-1", "work", "--preflight-skip", "a=b"), "Vorlauf"),
    ],
)
def test_invalid_call_exits_2(flow_file, args, message):
    result = _step(flow_file, *args)
    assert result.exit_code == 2
    assert message in result.stderr


def test_invalid_answer_exits_2(flow_file, tmp_path):
    (tmp_path / "bad.json").write_text("[]")
    result = _step(flow_file, "x-1", "work", "work=bad.json")
    assert result.exit_code == 2
    assert "kein Objekt" in result.stderr


def test_flow_option_routes_step_by_path(flow_file, capsys):
    with pytest.raises(SystemExit) as raised:
        main(["-f", "./entwurf.toml", "step", "x-1", "work"])
    out, err = capsys.readouterr()
    assert raised.value.code == 0
    assert out.startswith("Schritt: local")
    assert "entwurf.toml" in err


def test_flow_without_ops_has_no_step_package(flow_file):
    flow = load_flow_file(flow_file)
    with pytest.raises(FlowError, match="kein ops-Modul für step"):
        load_package_ops(type(flow)(**{**flow.__dict__, "ops": None}))
