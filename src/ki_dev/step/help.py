"""Hilfetexte von ``ki-dev -f ABLAUF step`` und ``ki-dev step``."""

from __future__ import annotations

HELP = """\
Eine Übergabe eines Ablaufs ausgeben (Executor manual, zustandslos).

AUFRUF
  ki-dev -f ABLAUF step BEAD_ID ZUSTAND [ZUSTAND=DATEI ...]
    ABLAUF wie bei -f (Name oder Pfad), ZUSTAND ein Zustand mit
    Übergabe (turn/ask; ki-dev flow show ABLAUF zeigt sie).
    Ohne Antwort für ZUSTAND: seine Übergabe. Mit ZUSTAND=DATEI: die
    Ops des Pakets deuten die Antwort, der Ablauf nimmt die Kante,
    step fährt Maschinenzustände (Vorlauf) und gibt die nächste
    Übergabe aus oder das Ende.
    Weitere ZUSTAND=DATEI liefern Laufdaten von weiter vorn (die
    Datei ist die Antwort dieses Zustands); fehlt eine, die der
    Ablauf deklariert (input), Exit 2 mit Name und Herkunft.
    DATEI - liest stdin. Nichts wird gespeichert.

BEISPIELE
  ki-dev -f map step projekt-42 map
  ki-dev -f map step projekt-42 map.review
  ki-dev -f map step projekt-42 map.review map.review=review.json
  ki-dev -f map step projekt-42 map.correction \\
    map.correction=done.json
  ki-dev -f implement_review step projekt-42 implement \\
    implement=done.json --preflight-skip 'lint=nur Doku'
  ki-dev -f implement_review step projekt-42 implement.review \\
    implement.review=review.json implement.preflight=vorlauf.json

ANTWORTEN (Review-Muster)
  Schreiben, Korrektur: {} oder {"feedback": "…"} (höchstens
  feedback_max_chars Zeichen, Standard 600). Review: {"event",
  "detail", "requirement_ref"}, optional preflight_args/
  preflight_skip. Entscheidung: {"event": "accept"} u. a.

VORLAUF
  Bindet der Ablauf checks.preflight, läuft der Vorlauf, wenn der
  Ablauf ihn erreicht (Korrekturen können Dateien ändern;
  pyproject.toml, tool.ki-dev.handoff.preflight).
  --preflight-args NAME=ARGS hängt ARGS einmalig an die Prüfung NAME
  an; --preflight-skip NAME=GRUND lässt sie begründet aus (beide
  wiederholbar). Beides ergibt einen Teillauf: Review ja, PASS nein.

BASISGRENZE
  Die gerenderte Basisübergabe (ohne Leitlinien und Prüfbericht) hat
  höchstens base_max_chars Unicode-Zeichen (Standard 4000, in
  pyproject.toml, Abschnitt tool.ki-dev.handoff). Zu lang: Exit 2, kein
  stdout, nie gekürzt.

Ausgabe kopieren und in einer neuen Agentensitzung einfügen.
Der Befehl startet keinen Agenten.

Details: docs/step.de.md
"""

TOOL_HELP = """\
Übergaben ohne Ablaufposition: freie lokale Sitzung oder
Sitzungsimport. Einen Bead führt ki-dev -f ABLAUF step BEAD_ID
ZUSTAND.

AUFRUFE
  ki-dev step local
    Allgemeine Übergabe für eine freie lokale Sitzung ohne Bead:
    feste Basis und die allgemeinen Abschnitte (common) der
    Regelquellen docs/policies/*.de.yaml. Ohne Bead, Datenbank und bd.
  ki-dev step map --agent codex --session SESSION_ID --title TITEL
    Codex- oder Claude-Sitzung als Quelle importieren: datierter
    Snapshot unter .local/var/transcripts/ (YYMMDDTHH_titel_sid8.jsonl),
    Quellen-Bead (bei gleichem Stand wiederverwendet) und die
    Kartierungsübergabe. --title ist Pflicht und ergibt den
    Dateinamen.

BEISPIELE
  ki-dev step local > uebergabe.txt
  ki-dev step map --agent claude --session SESSION_ID --title 'Docker'

Details: docs/step.de.md
"""
