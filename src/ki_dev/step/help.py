"""Hilfetext von ``ki-dev step``."""

from __future__ import annotations

HELP = """\
Eine Arbeitsübergabe für eine neue Agentensitzung ausgeben.

AUFRUFE
  ki-dev step BEAD_ID --step STEP
    Übergabe aus einem vorhandenen Bead erstellen (beginnt dort).
  ki-dev step BEAD_ID
    Gespeicherten Zustand fortsetzen (.local/handoff/steps/BEAD_ID):
    nach dem Schreiben folgt das Review, nach der Korrektur die
    Folgerunde, sonst die Folgeschritte für den Menschen.
  ki-dev step map --agent codex --session SESSION_ID --title TITEL
    Codex- oder Claude-Sitzung als Quelle importieren und Kartierung
    vorbereiten.
  ki-dev step local
    Allgemeine Übergabe für eine freie lokale Sitzung ohne Bead.

SCHRITTE (--step)
  map          Anforderungen aus Rohnotizen kartieren.
  graph        Aus der Karte einzelne Vorgänge ableiten.
  materialize  Einen Vorgang ausführungsreif beschreiben.
  implement    Den beschriebenen Auftrag umsetzen.
  review       Ein Ergebnis in einer getrennten Sitzung prüfen.

BEISPIELE
  ki-dev step projekt-42 --step map
  ki-dev step projekt-42 --step graph
  ki-dev step projekt-42 --step materialize
  ki-dev step projekt-42 --step implement > uebergabe.txt
  ki-dev step projekt-42 --step review
  ki-dev step projekt-42 --step review --preflight-args 'tests=-k x'
  ki-dev step projekt-42 --step review --preflight-skip 'lint=nur Doku'
  ki-dev step projekt-42 --step review --review-of materialize
  ki-dev step projekt-42 --step review --next-turn
  ki-dev step projekt-42 --step review --next-turn --feedback-file -
  ki-dev step projekt-42 --step review --next-turn --decision-file -
  ki-dev step projekt-42
  ki-dev step map --agent claude --session SESSION_ID --title 'Docker'
  ki-dev step local > uebergabe.txt

REVIEW
  Standard: implement. Führt vorab konfigurierte Korrekturen und Tests
  aus. Korrekturen können Dateien ändern. Konfiguration: pyproject.toml,
  tool.ki-dev.handoff.preflight.
  --preflight-args NAME=ARGS hängt ARGS einmalig an die Prüfung NAME
  an; --preflight-skip NAME=GRUND lässt sie begründet aus (beide
  wiederholbar, auch mit --next-turn). Beides ergibt einen Teillauf:
  Zwischenreview ja, PASS nein.
  --review-of map, graph oder materialize: nur lesen, ohne Vorlauf.

NÄCHSTE NACHRICHT (--step review --next-turn)
  Nach einer Korrektur: Vorlauf (Ziel implement) fehlgeschlagen ->
  Nachricht an den Umsetzer (stdout, Exit 1); bestanden oder map/graph/
  materialize -> erneute Review-Nachricht (Exit 0).
  --feedback-file DATEI|- hängt eine Rückmeldung des Schreibagenten an
  (UTF-8; - liest stdin; höchstens feedback_max_chars Zeichen, Standard
  600, in pyproject.toml, Abschnitt tool.ki-dev.handoff; nie gekürzt).
  Ohne die Option wird nichts gelesen.
  --decision-file DATEI|- liest stattdessen die JSON-Antwort der
  Umsetzungs-Review (event, detail, requirement_ref, attempt; attempt
  ist die Kennung aus der Zeile "Versuch:" der Übergabe, eine Antwort
  gilt nur für ihren Versuch; höchstens 20000 Zeichen) und gibt ohne
  Vorlauf die Nachricht laut Planungsablauf aus: fix (CHANGES) ->
  Umsetzer, sonst -> Mensch. PASS nach einem Teillauf weist der
  Ablauf ab. Ungültig oder zu einem früheren Versuch gehörig: Exit 2.

BASISGRENZE
  Die gerenderte Basisübergabe (ohne Leitlinien und Prüfbericht) hat
  höchstens base_max_chars Unicode-Zeichen (Standard 4000, in
  pyproject.toml, Abschnitt tool.ki-dev.handoff). Zu lang: Exit 2, kein
  stdout, nie gekürzt; bei map bleiben Quelle und Quellen-Bead erhalten.
  Gilt nicht für --next-turn.

LEITLINIEN
  Beide Formen hängen nach der Übergabe (und nach Lesehinweis bzw.
  Prüfbericht) die für den Schritt geltenden Regeltexte aus
  docs/policies/*.de.yaml an: gesonderter Block, nie gekürzt, nicht Teil
  der Basisübergabe; die gesamte Ausgabe kann daher länger sein.
  Fehlende Quelle Exit 1, ungültige Quelle Exit 2 (vor jedem Vorlauf).

LOKALE ÜBERGABE (local)
  Ohne Bead, Datenbank und bd im PATH, ohne --step und weitere Optionen
  (sonst Exit 2). Gibt eine feste Basis und die allgemeinen Abschnitte
  (common) der Regelquellen docs/policies/*.de.yaml aus: Lesebefehle,
  Rollenrechte, Python/pytest, Messregeln und allgemeine Leitlinien.
  Die Basisgrenze gilt wie sonst nur für die Basis.

SITZUNGSIMPORT (map --agent codex --session SESSION_ID --title TITEL)
  Schreibt einen datierten Snapshot unter .local/var/transcripts/
  (YYMMDDTHH_titel_sid8.jsonl) und legt einen Quellen-Bead an (bei
  gleichem Stand wiederverwendet). --title ist Pflicht und ergibt den
  Dateinamen. SESSION_ID durch die ID ersetzen.
  Statt einer Beads-ID; nicht mit --step kombinieren.

Ausgabe kopieren und in einer neuen Agentensitzung einfügen.
Der Befehl startet keinen Agenten.

Details zu Pflichtfeldern, Konfiguration und Fehlern: docs/step.de.md
"""
