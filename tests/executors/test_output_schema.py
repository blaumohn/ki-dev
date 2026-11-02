"""Antwortschema an der CLI-Grenze: Übergabe je CLI und Antwortpfad mit
Fixtures aus echten Aufrufen (Claude Code 2.1.316, codex 0.166.0, Haiku
bzw. Luna, Ablaufschema von ``implement``)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from ki_dev.adapter.agent import AgentReviewer, AgentWorker
from ki_dev.adapter.contract import (
    ReviewRequest,
    RunTask,
    WorkRequest,
)
from ki_dev.adapter.executors import (
    ClaudeCliAdapter,
    CodexCliAdapter,
    Effort,
    TurnRequest,
    TurnResult,
    TurnStatus,
)
from ki_dev.adapter.executors.metering import (
    claude_result,
    claude_stream,
    codex_result,
)
from ki_dev.flow_ops.implement.review_output import (
    REVIEW_VOCABULARY,
    parse_review_decision,
)

from .conftest import FakeRunner

FIXTURES = Path(__file__).parent.parent / "golden" / "executors"
SCHEMA = {"type": "object", "properties": {"a": {"type": "string"}}}


def _request(**over: object) -> TurnRequest:
    base = {
        "session_id": "01J-session",
        "message": "m",
        "model": "x",
        "effort": Effort.LOW,
        "workdir": Path("/work"),
    }
    base.update(over)
    return TurnRequest(**base)  # type: ignore[arg-type]


def _turn(stdout: str) -> TurnResult:
    return TurnResult(
        status=TurnStatus.OK,
        exit_code=0,
        stdout=stdout,
        stderr="",
        argv=(),
        duration_s=1.0,
    )


# --- Übergabe an die CLI --------------------------------------------


def test_claude_gets_the_schema_as_argument():
    runner = FakeRunner()
    ClaudeCliAdapter(runner=runner).send_turn(
        _request(output_schema=SCHEMA)
    )
    index = runner.argv.index("--json-schema")
    assert json.loads(runner.argv[index + 1]) == SCHEMA


@pytest.mark.parametrize("session", ["01J-session"])
def test_codex_reads_the_schema_from_a_file_for_this_call_only(session):
    """Die Datei existiert während des Aufrufs, außerhalb des Worktrees,
    und ist danach weg; ``-`` bleibt das letzte Argument."""
    seen = {}

    def runner(argv, **kwargs):
        index = argv.index("--output-schema")
        path = Path(argv[index + 1])
        seen.update(
            path=path,
            content=json.loads(path.read_text(encoding="utf-8")),
            argv=argv,
            cwd=kwargs["cwd"],
        )
        return _turn("")

    CodexCliAdapter(runner=runner).send_turn(
        _request(session_id=session, output_schema=SCHEMA)
    )
    assert seen["content"] == SCHEMA
    assert seen["argv"][-1] == "-"
    assert seen["argv"][1:3] == ["exec", "resume"]
    assert not seen["path"].is_relative_to(seen["cwd"])
    assert not seen["path"].exists()


def test_codex_schema_file_is_removed_after_a_failing_runner():
    seen = []

    def runner(argv, **_kwargs):
        seen.append(Path(argv[argv.index("--output-schema") + 1]))
        raise OSError("Start gescheitert")

    with pytest.raises(OSError, match="Start"):
        CodexCliAdapter(runner=runner).send_turn(
            _request(output_schema=SCHEMA)
        )
    assert seen
    assert not seen[0].exists()


@pytest.mark.parametrize(
    ("adapter", "option"),
    [
        (ClaudeCliAdapter, "--json-schema"),
        (CodexCliAdapter, "--output-schema"),
    ],
)
def test_without_schema_there_is_no_option(adapter, option):
    runner = FakeRunner()
    adapter(runner=runner).send_turn(_request())
    assert option not in runner.argv


def test_output_schema_must_be_a_mapping():
    with pytest.raises(TypeError, match="output_schema"):
        _request(output_schema="{}")


# --- Rollen ---------------------------------------------------------


class _Spy:
    def __init__(self) -> None:
        self.request = None

    def send_turn(self, request):
        self.request = request
        return replace(_turn('{"outcome":"completed","summary":"s"}'))


def _task(tmp_path) -> RunTask:
    return RunTask(
        "r",
        "Auftrag",
        (),
        tmp_path,
        "write",
        acceptance_criteria=("K",),
    )


def test_reviewer_passes_the_schema_read_only(tmp_path):
    spy = _Spy()
    reviewer = AgentReviewer(
        spy, "s", "m", Effort.LOW, spec=None  # type: ignore[arg-type]
    )
    reviewer.review(
        ReviewRequest(
            _task(tmp_path), 1, "p", REVIEW_VOCABULARY, "a", SCHEMA
        )
    )
    assert spy.request.output_schema == SCHEMA


def test_worker_stays_without_schema(tmp_path):
    """Entscheidung in ki-dev-ablauf-99zv: der Worker-Vertrag bleibt."""
    spy = _Spy()
    worker = AgentWorker(
        spy, "s", "m", Effort.LOW, spec=None  # type: ignore[arg-type]
    )
    worker.work(WorkRequest(_task(tmp_path), 1, "p", "a"))
    assert spy.request.output_schema is None


# --- Antwortpfad mit Fixtures aus echten Aufrufen -------------------


@pytest.mark.parametrize(
    ("name", "observations"),
    [("claude-new", ("Beispiel",)), ("claude-resume", ())],
)
def test_real_claude_answer_passes_the_contract(name, observations):
    raw = (FIXTURES / f"{name}-structured.jsonl").read_text()
    line, _quota = claude_stream(raw)
    assert json.loads(line)["structured_output"]
    result = claude_result(_turn(line))
    assert result.ok
    decision = parse_review_decision(
        result.stdout, run_id="live", round_id=1
    )
    assert decision.event == "PASS"
    assert decision.observations == observations


@pytest.mark.parametrize(
    ("name", "observations"),
    [("codex-new", ("Beispiel",)), ("codex-resume", ())],
)
def test_real_codex_answer_passes_the_contract(name, observations):
    raw = (FIXTURES / f"{name}-structured.jsonl").read_text()
    result = codex_result(_turn(raw))
    assert result.ok
    decision = parse_review_decision(
        result.stdout, run_id="live", round_id=1
    )
    assert decision.event == "PASS"
    assert decision.observations == observations


def _claude_line() -> str:
    path = FIXTURES / "claude-new-structured.jsonl"
    return path.read_text().strip()


def test_claude_prefers_the_structured_answer_over_the_model_text():
    """``result`` kann Modelltext sein; maßgeblich ist das Objekt."""
    line = _claude_line()
    event = {**json.loads(line), "result": "Fertig, siehe oben."}
    result = claude_result(_turn(json.dumps(event)))
    assert json.loads(result.stdout) == event["structured_output"]


def test_claude_without_schema_keeps_the_text():
    line = _claude_line()
    event = json.loads(line)
    del event["structured_output"]
    event["result"] = "freier Text"
    result = claude_result(_turn(json.dumps(event)))
    assert result.stdout == "freier Text"


def test_rejected_schema_is_a_visible_failure():
    """So meldet die API ein oberstes ``allOf`` (live beobachtet)."""
    line = _claude_line()
    event = {
        **json.loads(line),
        "is_error": True,
        "result": "API Error: 400 tools.4.custom.input_schema: ...",
    }
    del event["structured_output"]
    result = claude_result(_turn(json.dumps(event)))
    assert not result.ok
    assert "API Error: 400" in result.error
