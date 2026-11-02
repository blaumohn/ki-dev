"""Übergaben im einen Ausführer (ki-dev-ablauf-ige.6.1–6.3).

Derselbe Ablauf läuft mit Agenten (hier mock) ohne Halt bis zum Ende;
mit dem Boten hält er in ``awaiting_input`` und setzt mit der Antwort
fort. Ein neuer Lauf im selben Protokoll beginnt
mit ``lauf --@start--> lauf``.
"""

from __future__ import annotations

import copy
import json
import re

import pytest

from ki_dev.adapter.agent import AgentSession
from ki_dev.adapter.contract import AnswerPending
from ki_dev.adapter.executors import ClaudeCliAdapter, Effort
from ki_dev.adapter.executors.contract import (
    QuotaMeasurement,
    QuotaStatus,
    TurnResult,
    TurnStatus,
)
from ki_dev.adapter.mock import MockAnswers
from ki_dev.flow.binding import OperationSpec
from ki_dev.flow.model import parse_flow, read_raw
from ki_dev.flow_ops.review.model import ReviewModel
from ki_dev.run_store import RunStore, RunStoreError
from ki_dev.runner.bound import BoundOperations
from ki_dev.runner.dispatch import Dispatch, role_of
from ki_dev.runner.events import check_conformance
from ki_dev.runner.meter import Meter
from ki_dev.runner.package import PackageRunner
from ki_dev.runner.protocol import RUN_DOC
from ki_dev.runner.safety import CallLedger
from ki_dev.usage import (
    CounterScope,
    TokenCounts,
    UsageEvent,
    UsageStatus,
)
from tests.executor_specs import BOOKED, LOCAL, spec_for
from tests.executors.usage_fakes import write_usage_cli


def _flow():
    """implement_review mit einem Vorlauf, dessen Tatsachen in die
    Laufdaten gehen."""
    raw = copy.deepcopy(read_raw("implement_review"))
    raw["op"]["checks"]["output"] = {"facts": ["facts"]}
    return parse_flow(raw)


FLOW = _flow()


def _catalog(facts=("full_checks",)):
    def checks():
        return {"event": "checks_passed", "facts": list(facts)}

    return {
        "checks.preflight": OperationSpec(
            checks, {"type": "array", "maxItems": 0}, {"type": "object"}
        )
    }


def _read(handoff, answer):
    """Antwort → Ereignis."""
    value = json.loads(answer)
    assert value["attempt"] == handoff.attempt
    return {}, value["event"]


def _runner(tmp_path, executors, catalog=None):
    turns = Dispatch(
        FLOW,
        executors,
        render=lambda h: f"Übergabe {h.state} {h.attempt}",
        read=_read,
        workdir=tmp_path,
    )
    return PackageRunner(
        FLOW,
        BoundOperations(FLOW.bindings, catalog or _catalog()),
        RunStore(tmp_path, "b"),
        model=ReviewModel,
        turns=turns,
    )


def _answer(event):
    return json.dumps({"attempt": "{attempt}", "event": event})


class Inbox:
    """Bote: gibt aus, antwortet erst, wenn eine Antwort vorliegt."""

    spec = LOCAL

    def __init__(self):
        self.answers = {}
        self.prompts = []

    def ask(self, request):
        if request.key in self.answers:
            return self.answers.pop(request.key)
        self.prompts.append(request.prompt)
        raise AnswerPending("Antwort fehlt")


def test_roles_come_from_the_flow():
    assert role_of(FLOW, "implement") == "worker"
    assert role_of(FLOW, "implement.review") == "review"
    assert role_of(FLOW, "implement.decision") is None


def test_agents_run_the_flow_to_the_end(tmp_path):
    worker = MockAnswers(LOCAL, [_answer("done"), _answer("done")])
    review = MockAnswers(LOCAL, [_answer("fix"), _answer("PASS")])
    run = _runner(tmp_path, {"worker": worker, "review": review})
    result = run.start({})
    assert result["status"] == result["state"] == "finished"
    assert [p.split()[1] for p in worker.prompts] == [
        "implement",
        "implement.correction",
    ]
    assert [p.split()[1] for p in review.prompts] == [
        "implement.review",
        "implement.review",
    ]
    attempts = [p.split()[2] for p in worker.prompts + review.prompts]
    assert attempts == ["b:1", "b:3", "b:2", "b:4"]


def test_messenger_halts_and_the_answer_resumes(tmp_path):
    inbox = Inbox()
    review = MockAnswers(LOCAL, [_answer("PASS")])
    run = _runner(tmp_path, {"worker": inbox, "review": review})
    halt = run.start({})
    assert (halt["status"], halt["state"]) == (
        "awaiting_input",
        "implement",
    )
    assert halt["attempt"] == "b:1"
    assert inbox.prompts == ["Übergabe implement b:1"]
    inbox.answers["b:1"] = _answer("done").replace("{attempt}", "b:1")
    done = run.resume()
    assert done["state"] == "finished"
    assert [(t.source, t.event) for t in done["path"]] == [
        ("implement", "done"),
        ("implement.preflight", "checks_passed"),
        ("implement.review", "PASS"),
    ]


def test_start_at_a_state(tmp_path):
    review = MockAnswers(LOCAL, [_answer("PASS")])
    run = _runner(tmp_path, {"worker": Inbox(), "review": review})
    result = run.start({}, "implement.preflight")
    assert result["state"] == "finished"
    assert result["path"][0].source == "implement.preflight"


def test_role_without_executor_is_a_visible_error(tmp_path):
    run = _runner(tmp_path, {"review": Inbox()})
    with pytest.raises(RunStoreError, match="kein Executor"):
        run.start({})


def _review_waits(tmp_path, catalog=None):
    """Lauf ab dem Vorlauf, der Bote hält im Review."""
    run = _runner(
        tmp_path, {"worker": Inbox(), "review": Inbox()}, catalog
    )
    halt = run.start({}, "implement.preflight")
    assert (halt["status"], halt["state"]) == (
        "awaiting_input",
        "implement.review",
    )
    return run


def test_answer_names_the_executor_in_the_log(tmp_path):
    review = MockAnswers(LOCAL, [_answer("PASS")])
    run = _runner(tmp_path, {"worker": Inbox(), "review": review})
    run.start({}, "implement.preflight")
    rows = [
        (e["state"], e["adapter"])
        for e in run.store.load_events()
        if e["region"] == "ablauf"
    ]
    assert rows == [
        ("implement.preflight", "ki-dev"),
        ("implement.review", LOCAL.name),
    ]


def test_new_run_starts_again_with_fresh_operations(tmp_path):
    """again: Neubeginn im selben Protokoll; der Vorlauf läuft erneut,
    statt das Ergebnis des alten Laufs wiederzuverwenden."""
    _review_waits(tmp_path)
    artifacts = tmp_path / "b" / "artifacts"
    assert len(list(artifacts.iterdir())) == 1
    run = _review_waits_again(tmp_path)
    assert len(list(artifacts.iterdir())) == 2
    events = run.store.load_events()
    assert [e["event"] for e in events if e["region"] == "lauf"] == [
        "@start"
    ]
    # Die Regionen des Laufs beginnen neu (konform); nur der Ablauf
    # springt vom Review zurück in den Vorlauf.
    problems = check_conformance(FLOW, events, RUN_DOC)
    assert [p.split(": ")[1] for p in problems] == [
        "keine Kante implement.review --@jump--> implement.preflight"
    ]


def _review_waits_again(tmp_path):
    run = _runner(tmp_path, {"worker": Inbox(), "review": Inbox()})
    halt = run.start({}, "implement.preflight", again=True)
    assert halt["state"] == "implement.review"
    return run


def test_new_run_elsewhere_is_a_jump(tmp_path):
    _review_waits(tmp_path)
    run = _runner(tmp_path, {"worker": Inbox(), "review": Inbox()})
    run.start({}, "implement", again=True)
    events = run.store.load_events()
    jump = [i for i, e in enumerate(events) if e["event"] == "@jump"]
    assert check_conformance(FLOW, events, RUN_DOC) == [
        f"{jump[0]}: keine Kante implement.review --@jump--> implement"
    ]


# --- Budget: Reservierung vor start, Buchung nach ask (ige.6.4.4) ----

USAGE = {
    "input_tokens": 10,
    "output_tokens": 20,
    "cache_read_input_tokens": 0,
    "cache_creation_input_tokens": 0,
}


def _event():
    return UsageEvent(
        UsageStatus.MEASURED,
        "fake",
        "cli_result",
        CounterScope.CALL_TOTAL,
        cli_version="2.1.272",
        session_id="sess-1",
        tokens=TokenCounts(
            fresh_input=10, cache_read=0, cache_creation=0, output=20
        ),
    )


class Booked:
    """Testdoppel mit gebuchtem Aufruf: gibt Ereignisse aus, meldet
    Verbrauch über ``last_result`` oder scheitert mit ``error``."""

    spec = BOOKED
    session_id = "sess-1"

    def __init__(self, events=(), *, usage=USAGE, error=None):
        self.events = list(events)
        self.usage = usage
        self.error = error
        self.prompts = []
        self.last_result = None
        self.seen_call_id = None
        self.seen_files = None
        self.store = None

    def ask(self, request):
        self.prompts.append(request.prompt)
        record = self.store.load_record()
        self.seen_call_id = record["pending"]["call_id"]
        self.seen_files = sorted(
            p.name for p in (self.store.run_dir / "calls").iterdir()
        )
        failed = self.error is not None
        self.last_result = TurnResult(
            TurnStatus.NONZERO_EXIT if failed else TurnStatus.OK,
            1 if failed else 0,
            "",
            "",
            (),
            1.0,
            error=str(self.error) if failed else None,
            usage=self.usage,
            usage_event=_event(),
        )
        if self.error is not None:
            raise self.error
        event = self.events.pop(0)
        return json.dumps({"attempt": request.key, "event": event})


def _booked_runner(tmp_path, executors, catalog=None):
    store = RunStore(tmp_path, "b")
    for executor in executors.values():
        if isinstance(executor, Booked):
            executor.store = store
    turns = Dispatch(
        FLOW,
        executors,
        render=lambda h: f"Übergabe {h.state} {h.attempt}",
        read=_read,
        workdir=tmp_path,
        meter=Meter(store, executors),
        ledger=CallLedger(store),
    )
    return PackageRunner(
        FLOW,
        BoundOperations(FLOW.bindings, catalog or _catalog()),
        store,
        model=ReviewModel,
        turns=turns,
    )


def _calls(tmp_path):
    return tmp_path / "b" / "calls"


def test_budget_reserves_before_start_and_books_after_ask(tmp_path):
    """AC1: nach start steht die Kennung im Datensatz, die Reservierung
    liegt vor dem Aufruf; nach dem Aufruf sind Verbrauch und Abschluss
    gebucht."""
    worker = Booked(["done"])
    review = MockAnswers(LOCAL, [_answer("PASS")])
    run = _booked_runner(tmp_path, {"worker": worker, "review": review})
    done = run.start({}, "implement")

    assert done["status"] == "finished"
    assert re.fullmatch(r"op-\d{8,}-[0-9a-f]{32}", worker.seen_call_id)
    call_id = worker.seen_call_id
    assert worker.seen_files == [f"{call_id}-start.json"]
    assert (_calls(tmp_path) / f"{call_id}-result.json").exists()
    store = RunStore(tmp_path, "b")
    assert len(store.load_usage(call_id)) == 1
    report = CallLedger(store).usage_report()
    assert report.total == TokenCounts(10, 0, 0, 20).total


def test_failing_ask_books_usage_then_stops_with_the_reason(tmp_path):
    """AC2: Verbrauch vor dem Abschluss, der Abschluss trägt den
    Fehlertext; der Lauf hält, statt einen Fehler durchzureichen."""
    worker = Booked(error=RuntimeError("boom"))
    review = MockAnswers(LOCAL, [_answer("PASS")])
    run = _booked_runner(tmp_path, {"worker": worker, "review": review})
    halt = run.start({}, "implement")

    assert halt["status"] == "stopped"
    assert halt["reason"] == "RuntimeError: boom"
    call_id = worker.seen_call_id
    result = json.loads(
        (_calls(tmp_path) / f"{call_id}-result.json").read_text()
    )
    assert result["error"] == "RuntimeError: boom"
    assert len(RunStore(tmp_path, "b").load_usage(call_id)) == 1


def test_crash_between_start_and_artifact_is_uncertain_then_reconciled(
    tmp_path,
):
    """AC3: Absturz nach start (hier: Abbruch in ask) ergibt uncertain;
    der Abgleich bucht den Nachweis über ledger.reconcile."""
    worker = Booked(error=KeyboardInterrupt())
    review = MockAnswers(LOCAL, [_answer("PASS")])
    run = _booked_runner(tmp_path, {"worker": worker, "review": review})
    with pytest.raises(KeyboardInterrupt):
        run.start({}, "implement")
    call_id = worker.seen_call_id
    assert not (_calls(tmp_path) / f"{call_id}-result.json").exists()

    worker = Booked(["done"])
    review = MockAnswers(LOCAL, [_answer("PASS")])
    again = _booked_runner(
        tmp_path, {"worker": worker, "review": review}
    )
    assert again.resume()["status"] == "uncertain"
    done = again.reconcile(
        {"event": "done", "update": {}, "usage": USAGE}
    )
    assert done["status"] == "finished"
    result = json.loads(
        (_calls(tmp_path) / f"{call_id}-result.json").read_text()
    )
    assert result["usage"] == USAGE
    assert worker.prompts == []


@pytest.mark.parametrize(
    "usage",
    [
        {**USAGE, "cost_usd": -1},
        {**USAGE, "cost_usd": float("nan")},
        {k: v for k, v in USAGE.items() if k != "output_tokens"},
    ],
    ids=["negativ", "nan", "fehlend"],
)
def test_invalid_usage_is_a_gap_and_stops_before_the_next_call(
    tmp_path, usage
):
    """AC4: ein ungültiger Verbrauch hält den Lauf mit Lücke, ohne
    weiteren Agentenaufruf und ohne Ausnahme aus totals()."""
    worker = Booked(["done", "done"], usage=usage)
    review = MockAnswers(LOCAL, [_answer("fix")])
    run = _booked_runner(tmp_path, {"worker": worker, "review": review})
    halt = run.start({}, "implement")

    assert halt["status"] == "stopped"
    assert "Ungueltiger Verbrauch" in halt["reason"]
    assert len(worker.prompts) == 1


def test_seventh_call_is_stopped_by_the_guard_not_by_reserve(tmp_path):
    """AC5: sechs gebuchte Aufrufe, der siebte hält über within_limits;
    ask wird nicht aufgerufen."""
    store = RunStore(tmp_path, "b")
    ledger = CallLedger(store)
    ok = TurnResult(
        TurnStatus.OK, 0, "", "", (), 1.0, usage=USAGE
    )
    for number in range(6):
        ledger.reserve(f"old-{number}", "worker", True, "fake")
        ledger.finish(f"old-{number}", ok, None)

    worker = Booked(["done"])
    review = MockAnswers(LOCAL, [_answer("PASS")])
    run = _booked_runner(tmp_path, {"worker": worker, "review": review})
    halt = run.start({}, "implement")

    assert halt["status"] == "stopped"
    assert "Aufrufgrenze erreicht: 6" in halt["reason"]
    assert worker.prompts == []


def test_real_adapter_books_the_usage_from_the_cli_output(
    tmp_path, monkeypatch
):
    """AC6: echter Adapter mit Fake-CLI, ohne Fake-Executor: der
    Verbrauch kommt aus der Ausgabe der CLI und wird gebucht."""
    answer = json.dumps({"attempt": "b:1", "event": "done"})
    output = json.dumps({
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": answer,
        "session_id": "5d1b6e7a-0c3f-4a9e-8f2b-7c1d9e4a6b20",
        "num_turns": 1,
        "total_cost_usd": 0.2,
        "permission_denials": [],
        "usage": {
            "input_tokens": 10,
            "cache_read_input_tokens": 500,
            "cache_creation_input_tokens": 30,
            "output_tokens": 20,
        },
    })
    executable, trace = write_usage_cli(
        tmp_path,
        "claude",
        ClaudeCliAdapter.cli_version_pin,
        output,
        exit_code=0,
    )
    adapter = ClaudeCliAdapter(
        executable=str(executable), quota_dir=tmp_path / "quota"
    )
    monkeypatch.setattr(
        adapter,
        "measure_quota",
        lambda _session: QuotaMeasurement(
            QuotaStatus.MEASURED,
            used_percent=0.0,
            resets_at=9_999_999_999,
        ),
    )
    worker = AgentSession(
        adapter, None, "model", Effort.LOW, spec=spec_for(adapter)
    )
    review = MockAnswers(LOCAL, [_answer("PASS")])
    run = _booked_runner(tmp_path, {"worker": worker, "review": review})
    done = run.start({}, "implement")

    assert done["status"] == "finished", done.get("reason")
    assert trace.read_text().splitlines().count("turn") == 1
    store = RunStore(tmp_path, "b")
    report = CallLedger(store).usage_report()
    assert report.total == TokenCounts(10, 500, 30, 20).total
    (call,) = report.calls
    assert len(store.load_usage(call.call_id)) == 1


