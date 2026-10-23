"""Verlauf eines ``implement``-Laufs für Menschen.

``status`` nennt den Endzustand als JSON; ``history`` erklärt, wie er
entstand: je Runde geänderte Dateien, Prüfergebnisse, jede Antwort des
Reviews und davor eine Entscheidung des Menschen, danach Abschluss oder
Halt. Gelesen werden nur die Artefakte des Laufs (für Umsetzer und
Tests der letzte Versuch der Runde).

    Lauf version-fix: passed nach 2 Runden
      Runde 1  Umsetzer  geändert: version.py
      Runde 1  Tests     test_version fehlgeschlagen
      Runde 1  Review    decision: Test widerspricht dem Kriterium
      Runde 1  Mensch    AC2 geändert; Test ist veraltet
      Runde 1  Review    fix (AC2): test_version.py anpassen
      Runde 2  Umsetzer  geändert: test_version.py
      Runde 2  Tests     test_version bestanden
      Runde 2  Review    PASS
      Abschluss          Fast-forward integriert
"""

from __future__ import annotations

import re
from typing import cast

from ki_dev.flow_ops.implement.decisions import summary
from ki_dev.flow_ops.implement.runtime import read_run_status
from ki_dev.run_store import RunStore

# Operationen einer Runde: r0001-work-…, -evidence-…, -review-…
_ROUND_OPERATION = re.compile(r"^r(\d{4})-(work|evidence|review)-")
_INTEGRATION = re.compile(r"^final-integrate-")
WIDTH = 78


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
    for round_id, parts in sorted(rounds.items()):
        round_lines, seen = _round_lines(round_id, parts, seen)
        lines += round_lines
    if integration is not None:
        lines.append(_line("Abschluss", "", integration["detail"]))
    elif result.status != "passed":
        lines.append(_line("Halt", "", _halt(result.detail)))
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
) -> tuple[list[str], int]:
    """Umsetzer und Tests aus dem letzten Nachweisversuch der Runde,
    danach jedes Review-Urteil; eine Entscheidung des Menschen steht
    vor dem ersten Urteil, das sie erhalten hat (``seen``: so viele
    Entscheidungen kannten frühere Reviews schon)."""
    label = f"Runde {round_id}"
    lines = []
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
    for review in parts.get("review", []):
        known = review.get("decisions", [])
        lines += [
            _line(label, "Mensch", summary(document))
            for document in known[seen:]
        ]
        seen = max(seen, len(known))
        answer = _answer(review["decision"])
        lines.append(_line(label, "Review", answer))
    return lines, seen


def _halt(detail: str | None) -> str:
    """Grund des Halts; eine Entscheidung des Reviews nennt ihren
    Grund schon in der Review-Zeile."""
    return detail or "wartet auf Entscheidung (Bead ändern, resume)"


def _answer(decision: dict) -> str:
    """``fix (AC1): Befund`` oder ``PASS``: die Antwort des Reviews."""
    answer = decision["event"]
    if decision.get("requirement_ref"):
        answer += f" ({decision['requirement_ref']})"
    detail = decision["detail"].strip()
    return f"{answer}: {detail}" if detail else answer


def _changed(files: list[str]) -> str:
    if not files:
        return "keine Dateiänderung"
    return "geändert: " + ", ".join(files)


def _check(check: dict) -> str:
    outcome = "bestanden" if check["passed"] else "fehlgeschlagen"
    return f"{check['name']} {outcome}"


def _line(label: str, actor: str, text: str) -> str:
    """Eine Zeile, auf ``WIDTH`` Zeichen gekürzt (``…``)."""
    head = f"  {label:<9}{actor:<10}" if actor else f"  {label:<19}"
    text = " ".join(text.split())
    room = WIDTH - len(head)
    if len(text) > room:
        text = text[: room - 1].rstrip() + "…"
    return head + text
