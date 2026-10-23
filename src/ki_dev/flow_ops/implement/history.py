"""Verlauf eines ``implement``-Laufs für Menschen.

``status`` nennt den Endzustand als JSON; ``history`` erklärt, wie er
entstand: je Runde geänderte Dateien, Prüfergebnisse und die Antwort
des Reviews, danach der Abschluss. Gelesen werden nur die Artefakte
des Laufs (je Runde der letzte Versuch einer Operation).

    Lauf add-fix: passed nach 1 Runde
      Runde 1  Umsetzer  geändert: add.py
      Runde 1  Tests     test_add bestanden
      Runde 1  Review    PASS: add() addiert, beide Kriterien erfüllt
      Abschluss          Fast-forward integriert
"""

from __future__ import annotations

import re
from typing import cast

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
    for round_id, parts in sorted(rounds.items()):
        lines += _round_lines(round_id, parts)
    if integration is not None:
        lines.append(_line("Abschluss", "", integration["detail"]))
    return lines


def _artifacts(
    store: RunStore,
) -> tuple[dict[int, dict[str, dict]], dict | None]:
    """Je Runde die Artefakte nach Art; dazu das der Integration. Bei
    mehreren Versuchen gilt der letzte (sortierte Operations-IDs)."""
    rounds: dict[int, dict[str, dict]] = {}
    integration = None
    for operation_id in store.artifact_ids():
        artifact = cast(dict, store.load_artifact(operation_id))
        match = _ROUND_OPERATION.match(operation_id)
        if match:
            rounds.setdefault(int(match[1]), {})[match[2]] = artifact
        elif _INTEGRATION.match(operation_id):
            integration = artifact
    return rounds, integration


def _round_lines(round_id: int, parts: dict[str, dict]) -> list[str]:
    label = f"Runde {round_id}"
    lines = []
    evidence = parts.get("evidence")
    if evidence is not None:
        context = evidence["context"]
        files = [
            change["path"]
            for change in context["step_delta"]["git"]["files"]
        ]
        lines.append(_line(label, "Umsetzer", _changed(files)))
        lines += [
            _line(label, "Tests", _check(check))
            for check in context["checks"]
        ]
    review = parts.get("review")
    if review is not None:
        answer = _answer(review["decision"])
        lines.append(_line(label, "Review", answer))
    return lines


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
