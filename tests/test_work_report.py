"""Worker-Vertrag mit festen CLI-/Boten-Antworten ohne Modellaufrufe."""

import io
import json
from dataclasses import replace

import pytest

from ki_dev.adapter.agent import AgentWorker
from ki_dev.adapter.contract import (
    RunTask,
    WorkReport,
    WorkRequest,
    parse_work_report,
)
from ki_dev.adapter.executors import Effort
from ki_dev.adapter.manual import Console, ManualRelay
from ki_dev.adapter.mock import MockWorker
from ki_dev.flow.binding import BindingError
from ki_dev.flow_ops.implement.machine import IMPLEMENT
from ki_dev.flow_ops.implement.ops import ImplementationOperations
from ki_dev.runner.bound import BoundOperations
from ki_dev.runner.review_output import AgentProtocolError
from tests.executor_specs import BOOKED, LOCAL
from tests.test_role_sessions import OK, Executor


@pytest.fixture(params=["agent", "manual"])
def work(request, tmp_path):
    task = RunTask(
        "r-1",
        "Auftrag",
        (),
        tmp_path,
        "write",
        acceptance_criteria=("Ergebnis = 4",),
    )
    work_request = WorkRequest(task, 1, "bauen", "a-1")

    def answer(raw):
        if request.param == "agent":
            executor = Executor(
                replace(OK, stdout=raw, session_id="s-1")
            )
            worker = AgentWorker(
                executor, None, "m", Effort.LOW, spec=BOOKED
            )
        else:
            console = Console(
                lambda _: None, lambda: io.BytesIO(raw.encode())
            )
            worker = ManualRelay(console, "worker", LOCAL)
        return worker.work(work_request)

    return answer


@pytest.mark.parametrize(
    "outcome", ["completed", "needs_decision", "escalate"]
)
def test_structured_answers(work, outcome):
    raw = json.dumps(
        {"outcome": outcome, "summary": "Ergebnis 4; Test verlangt 5"}
    )
    assert work(raw) == WorkReport(
        "Ergebnis 4; Test verlangt 5", outcome
    )


def test_text_is_completed_without_keyword_detection(work):
    assert work("unmöglich; Zugriff fehlt") == WorkReport(
        "unmöglich; Zugriff fehlt"
    )
    assert work("fertig").outcome == "completed"


@pytest.mark.parametrize(
    "raw",
    [
        'Ich halte an.\n{"outcome":"needs_decision","summary":"Grund"}',
        'Ich halte an.\n\n{\n  "outcome": "needs_decision",\n'
        '  "summary": "Grund"\n}\n',
        'Vorab {kein JSON}.\nIch halte an.\n'
        '{"outcome":"needs_decision","summary":"Grund"}',
    ],
)
def test_report_after_leading_text_is_structured(work, raw):
    assert work(raw) == WorkReport("Grund", "needs_decision")


def test_report_in_one_code_block_is_structured(work):
    raw = '```json\n{"outcome":"needs_decision","summary":"Grund"}\n```'
    assert work(raw) == WorkReport("Grund", "needs_decision")


def test_braces_inside_text_remain_completed(work):
    raw = "Nutzt {a} intern.\nfertig"
    assert work(raw) == WorkReport(raw)


@pytest.mark.parametrize(
    "raw",
    [
        '{"outcome":"unknown","summary":"Grund"}',
        '{"outcome":null,"summary":"Grund"}',
        '{"outcome":[],"summary":"Grund"}',
        '{"outcome":"needs_decision","summary":"  "}',
        '{"outcome":"escalate","summary":42}',
        '{"outcome":"completed","summary":"ok","extra":true}',
        '{"summary":"ok"}',
        '{"outcome":"completed"}',
        '{"outcome":"escalate","outcome":"completed","summary":"Grund"}',
        '{"outcome":"escalate",',
        "[]",
        '```json\n{"outcome":"unknown","summary":"Grund"}\n```',
        'Ich halte an.\n{"outcome":"unknown","summary":"Grund"}',
        'Ich halte an.\n{"outcome":"escalate",',
        'Ich halte an.\n```json\n'
        '{"outcome":"escalate","summary":"Grund"}\n```',
        'Ich halte an.\n{"outcome":"escalate","summary":"Grund"}\n'
        "Danke.",
        'Ich halte an: "outcome" ist needs_decision.',
    ],
)
def test_invalid_structured_answers_are_protocol_errors(work, raw):
    with pytest.raises(AgentProtocolError):
        work(raw)


def test_empty_report_is_a_protocol_error():
    with pytest.raises(AgentProtocolError, match="nicht leer"):
        parse_work_report("  ")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"summary": " "},
        {"summary": None},
        {"summary": "Grund", "outcome": "unknown"},
    ],
)
def test_direct_reports_validate_the_contract(kwargs):
    with pytest.raises(ValueError):
        WorkReport(**kwargs)


def test_mock_remains_completed(tmp_path):
    task = RunTask(
        "r-1",
        "Auftrag",
        (),
        tmp_path,
        "write",
        acceptance_criteria=("K",),
    )
    report = MockWorker(LOCAL).work(
        WorkRequest(task, 1, "bauen", "a-1")
    )
    assert report.outcome == "completed"
    assert (tmp_path / "MOCK.md").read_text() == "Runde 1\n"


def test_stored_work_artifact_needs_event():
    """Kein Ersatzwert: ein abgeglichenes oder vor dem Worker-Halt
    gespeichertes Artefakt ohne ``event`` wird nicht zu completed."""
    catalog = ImplementationOperations(
        None, None, None, None, None
    ).catalog()
    operations = BoundOperations(IMPLEMENT.bindings, catalog)
    with pytest.raises(BindingError, match="op.work.output"):
        operations.accept("work", {"summary": "fertig"})
    assert operations.accept(
        "work", {"summary": "fertig", "event": "worker_escalate"}
    ) == ({"work_report": "fertig"}, "worker_escalate")
