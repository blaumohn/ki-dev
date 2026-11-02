"""Verlauf eines ``implement``-Laufs für Menschen.

``status`` nennt den Endzustand als JSON; ``history`` erklärt, wie er
entstand: je Runde eine Frage oder Eskalation des Umsetzers, geänderte
Dateien, Prüfergebnisse, jede Antwort des Reviews und die Entscheidung
des Menschen nach dem Halt, der sie verlangt hat; danach Abschluss oder
Halt. Gelesen werden nur die Artefakte des Laufs (für Umsetzer und
Tests der letzte Versuch der Runde). Zeilen sind auf ``WIDTH`` Zeichen
gekürzt; umbrochen werden nur Gründe, über die der Mensch entscheidet:
der Halt des Umsetzers und ``decision`` oder ``escalate`` des Reviews.
Antworten auf die Prüffragen und Beobachtungen des Reviews stehen
vollständig unter seinem Ereignis: Über sie entscheidet der Mensch, und
ein Mangel steht nicht immer in beiden.

    Lauf version-fix: passed nach 2 Runden
      Runde 1  Umsetzer  geändert: version.py
      Runde 1  Tests     test_version fehlgeschlagen
      Runde 1  Review    decision: Test widerspricht dem Kriterium
      Runde 1  Mensch    AC2 geändert; Test ist veraltet
      Runde 1  Review    fix (AC2): test_version.py anpassen
      Runde 2  Umsetzer  geändert: test_version.py
      Runde 2  Tests     test_version bestanden
      Runde 2  Review    PASS
                         invalid_input: totals() wirft bei -1
                         Beobachtung: limit_reasons lässt NaN durch
      Abschluss          Fast-forward integriert
      Offen              1 Beobachtung; vor `bd close` entscheiden
"""

from __future__ import annotations

import re
import textwrap
from typing import cast

from ki_dev.flow_ops.implement.decisions import summary
from ki_dev.flow_ops.implement.runtime import RunResult, read_run_status
from ki_dev.run_store import RunStore

# Operationen einer Runde: r0001-work-…, -evidence-…, -review-…
_ROUND_OPERATION = re.compile(r"^r(\d{4})-(work|evidence|review)-")
_INTEGRATION = re.compile(r"^final-integrate-")
# Halt des Umsetzers (Antwortvertrag): Art und Grund in eigener Zeile.
_WORKER_HALT = {
    "worker_needs_decision": "Frage",
    "worker_escalate": "Eskalation",
}
WIDTH = 78
REASON_LINES = 3
# Review-Antworten, nach denen der Mensch entscheidet: Grund umbrochen.
_REVIEW_HALTS = {"decision", "escalate"}
_DECISION_PENDING = "wartet auf Entscheidung (Bead ändern, resume)"


def run_history(store: RunStore) -> list[str]:
    """Zeilen des Verlaufs; der Lauf wird nur gelesen."""
    result = read_run_status(store)
    rounds, integration = _artifacts(store)
    count = len(rounds)
    lines = [
        f"Lauf {result.run_id}: {result.status} nach {count} "
        f"{'Runde' if count == 1 else 'Runden'}"
    ]
    seen = 0
    asked = None
    for round_id, parts in sorted(rounds.items()):
        round_lines, seen, asked = _round_lines(round_id, parts, seen)
        lines += round_lines
    if integration is not None:
        lines.append(_line("Abschluss", "", integration["detail"]))
        lines += _open_observations(rounds)
    elif result.status != "passed":
        lines.append(_line("Halt", "", _halt(result, asked)))
    return lines


def _artifacts(
    store: RunStore,
) -> tuple[dict[int, dict[str, list[dict]]], dict | None]:
    """Je Runde die Artefakte nach Art in Reihenfolge der (sortierten)
    Operations-IDs; dazu das der Integration."""
    rounds: dict[int, dict[str, list[dict]]] = {}
    integration = None
    for operation_id in store.artifact_ids():
        artifact = cast(dict, store.load_artifact(operation_id))
        match = _ROUND_OPERATION.match(operation_id)
        if match:
            parts = rounds.setdefault(int(match[1]), {})
            parts.setdefault(match[2], []).append(artifact)
        elif _INTEGRATION.match(operation_id):
            integration = artifact
    return rounds, integration


def _round_lines(
    round_id: int, parts: dict[str, list[dict]], seen: int
) -> tuple[list[str], int, str | None]:
    """Halte des Umsetzers, dann Umsetzer und Tests aus dem letzten
    Nachweisversuch der Runde, danach jedes Review-Urteil. Eine
    Entscheidung des Menschen steht nach dem Halt des Umsetzers der
    Runde, sonst vor dem ersten Urteil, das sie erhalten hat (``seen``:
    so viele Entscheidungen kannten frühere Reviews schon). Dazu der
    Grund eines noch offenen Halts des Umsetzers."""
    label = f"Runde {round_id}"
    lines = []
    halts = [
        work for work in parts.get("work", [])
        if work.get("event") in _WORKER_HALT
    ]
    for work in halts:
        kind = _WORKER_HALT[work["event"]]
        reason = f"{kind}: {work['summary']}"
        lines += _wrapped(label, "Umsetzer", reason)
    reviews = parts.get("review", [])
    if halts and reviews:
        known = reviews[0].get("decisions", [])
        lines += [
            _line(label, "Mensch", summary(document))
            for document in known[seen:]
        ]
        seen = max(seen, len(known))
    if parts.get("evidence"):
        context = parts["evidence"][-1]["context"]
        files = [
            change["path"]
            for change in context["step_delta"]["git"]["files"]
        ]
        lines.append(_line(label, "Umsetzer", _changed(files)))
        lines += [
            _line(label, "Tests", _check(check))
            for check in context["checks"]
        ]
    for review in reviews:
        known = review.get("decisions", [])
        lines += [
            _line(label, "Mensch", summary(document))
            for document in known[seen:]
        ]
        seen = max(seen, len(known))
        answer = _answer(review["decision"])
        if review["decision"]["event"] in _REVIEW_HALTS:
            lines += _wrapped(label, "Review", answer)
        else:
            lines.append(_line(label, "Review", answer))
        lines += _findings(label, review["decision"])
    open_halt = halts and not parts.get("evidence") and not reviews
    return lines, seen, halts[-1]["summary"] if open_halt else None


def _halt(result: RunResult, asked: str | None) -> str:
    """Grund des Halts; eine Entscheidung des Reviews oder eine Frage
    des Umsetzers (``asked``) nennt ihren Grund schon in ihrer Zeile."""
    detail = result.detail
    shown = asked is not None and asked in (detail or "")
    if not detail or (result.status == "waiting_decision" and shown):
        return _DECISION_PENDING
    return detail


def _answer(decision: dict) -> str:
    """``fix (AC1): Befund`` oder ``PASS``: die Antwort des Reviews."""
    answer = decision["event"]
    if decision.get("requirement_ref"):
        answer += f" ({decision['requirement_ref']})"
    detail = decision["detail"].strip()
    return f"{answer}: {detail}" if detail else answer


def _findings(label: str, decision: dict) -> list[str]:
    """Antworten und Beobachtungen vollständig unter dem Ereignis;
    Reviews vor den Prüffragen haben keine."""
    indent = " " * len(_head(label, "Review"))
    entries = [
        *(
            f"{name}: {answer}"
            for name, answer in decision.get("answers", {}).items()
        ),
        *(
            f"Beobachtung: {observation}"
            for observation in decision.get("observations", [])
        ),
    ]
    lines = []
    for entry in entries:
        rows = textwrap.wrap(
            " ".join(entry.split()),
            WIDTH - len(indent),
            subsequent_indent="  ",
        )
        lines += [indent + row for row in rows]
    return lines


def _open_observations(
    rounds: dict[int, dict[str, list[dict]]],
) -> list[str]:
    """Nach der Integration schließt nichts den Bead: Beobachtungen des
    letzten Reviews warten auf den Menschen."""
    reviews = rounds[max(rounds)].get("review", []) if rounds else []
    if not reviews:
        return []
    count = len(reviews[-1]["decision"].get("observations", []))
    if not count:
        return []
    noun = "Beobachtung" if count == 1 else "Beobachtungen"
    text = f"{count} {noun}; vor `bd close` entscheiden"
    return [_line("Offen", "", text)]


def _changed(files: list[str]) -> str:
    if not files:
        return "keine Dateiänderung"
    return "geändert: " + ", ".join(files)


def _check(check: dict) -> str:
    outcome = "bestanden" if check["passed"] else "fehlgeschlagen"
    return f"{check['name']} {outcome}"


def _line(label: str, actor: str, text: str) -> str:
    """Eine Zeile, auf ``WIDTH`` Zeichen gekürzt (``…``)."""
    head = _head(label, actor)
    text = " ".join(text.split())
    room = WIDTH - len(head)
    if len(text) > room:
        text = text[: room - 1].rstrip() + "…"
    return head + text


def _wrapped(label: str, actor: str, text: str) -> list[str]:
    """Wie :func:`_line`, aber umbrochen; Folgezeilen beginnen unter dem
    Text, nach ``REASON_LINES`` Zeilen gekürzt (``…``)."""
    head = _head(label, actor)
    room = WIDTH - len(head)
    rows = textwrap.wrap(" ".join(text.split()), room)
    if len(rows) > REASON_LINES:
        rows = rows[:REASON_LINES]
        rows[-1] = rows[-1][: room - 1].rstrip() + "…"
    indent = " " * len(head)
    return [head + rows[0], *(indent + row for row in rows[1:])]


def _head(label: str, actor: str) -> str:
    return f"  {label:<9}{actor:<10}" if actor else f"  {label:<19}"
