"""Verlauf von ``history`` aus dem Log lesen und für die README kürzen.

Der volle Verlauf nennt je Review auch die Antworten auf die Prüffragen
und die Beobachtungen und passt nicht in einen Auszug (höchstens 20
Zeilen, ``lib.sh``). Gekürzt bleibt jede Zeile eines Ereignisses
erhalten; eine gekürzte Stelle endet mit ``…``.
"""

from __future__ import annotations

import re

ROWS = ("  Runde ", "  Halt ", "  Abschluss ", "  Offen ", " " * 21)
# Antwort auf eine Prüffrage oder Beobachtung, mit Folgezeilen tiefer
# eingerückt (flow_ops/implement/history.py).
_FINDING = re.compile(r" {21}(?:[a-z_]+|Beobachtung): ")
_FOLLOWING = " " * 23


def rows(lines: list[str], start: int) -> list[str]:
    """Verlauf ab der Kopfzeile ``lines[start]``."""
    block = [lines[start]]
    for line in lines[start + 1 :]:
        if not line.startswith(ROWS):
            break
        block.append(line)
    return block


def compact(
    block: list[str], reasons: int = 0, findings: int = 0
) -> list[str]:
    """Je Ereignis ``reasons`` Folgezeilen des Grunds; im ganzen Auszug
    ``findings`` Zeilen mit Antworten und Beobachtungen."""
    result: list[str] = []
    kept = 0
    in_finding = False
    for line in block:
        if not line.startswith(" " * 21):
            result.append(line)
            kept = 0
            in_finding = False
            continue
        in_finding = bool(
            _FINDING.match(line)
            or (in_finding and line.startswith(_FOLLOWING))
        )
        if in_finding and findings > 0:
            result.append(line)
            findings -= 1
        elif not in_finding and kept < reasons:
            result.append(line)
            kept += 1
        else:
            result[-1] = _cut(result[-1])
    return result


def fit(block: list[str], room: int, reasons: int = 0) -> list[str]:
    """Wie :func:`compact`, mit so vielen Antworten und Beobachtungen,
    wie in ``room`` Zeilen passen."""
    base = len(compact(block, reasons))
    return compact(block, reasons, max(0, room - base))


def _cut(line: str) -> str:
    return line if line.endswith("…") else line + "…"
