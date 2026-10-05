---
layout: page
title: Arbeitsregeln für Agentensitzungen
permalink: /de/policies/arbeitsregeln/
---
<!-- Generiert aus docs/policies/arbeitsregeln.de.yaml mit scripts/render-guidelines.py; Änderungen dort vornehmen. -->

## Leitlinien und ihre Pflege

Bei Planung, Materialisierung, Umsetzung und Review gelten projektweit die
[Architektur- und Programmierleitlinien](programmierleitlinie.de.md)
(Struktur, Modulgrenzen, Konfiguration, gemeinsame deklarative Validierung)
und die [Technikleitlinie](technikleitlinie.de.md) (Werkzeugwahl für
Validierung mit `jsonschema` und externe Prozesse mit Plumbum).

Liefert eine `ki-dev handoff`-Übergabe Regeltexte mit, diese direkt
anwenden, ohne die Quelldokumente erneut vollständig zu lesen. Die lokale
Übergabe enthält nur die allgemeinen Abschnitte; die Phasenschwerpunkte
(Architektur in Planung und Materialisierung, Programmierung in Umsetzung
und Review, Docstrings) stehen in den verlinkten Seiten und werden vor
Arbeiten an diesen Bereichen dort gelesen. Die Regeln gelten unabhängig
von Epic-Zugehörigkeit und Handoff-Schritt; Epic-Hinweise ergänzen
bereichsspezifische Anforderungen.

Projektweite Regeln in `docs/policies/*.de.yaml` pflegen (die verlinkten
Seiten erzeugt `scripts/render-guidelines.py`), nicht in einzelnen
Aufträgen oder in AGENTS.md/CLAUDE.md duplizieren. Planung und
Materialisierung berücksichtigen insbesondere Zuständigkeiten,
Schnittstellen, Konfiguration, Datenverträge und Werkzeugwahl; Umsetzung
und Review prüfen zusätzlich die konkrete Codestruktur und
Fehlerbehandlung.

## Beads lesen

Aufgaben liegen in Beads (`bd`), nicht in Markdown-TODO-Listen. Eine
Bead-Übergabe nennt nur die ID; jede Rolle liest den Bead selbst:

```bash
bd show ID    # Bead lesen
bd ready      # verfügbare Arbeit finden
bd prime      # Beads-Kontext auffrischen
```

Schreibende Aufrufe wie `--claim` und `close` richten sich nach den
Rollenrechten des nächsten Abschnitts, nicht nach einem Beads-Block in
AGENTS.md/CLAUDE.md, den `bd init` oder `bd setup` neu eintragen können.
Die lokale Übergabe braucht weder Bead noch Datenbankverbindung.

## Manueller Handoff

Bei `ki-dev handoff` gehen die Rollenrechte aus Übergabe und diesem
Abschnitt einem Beads-Block vor (z. B. kein `--claim`/`close` für
Umsetzer). Den Beads-Status (`--claim`, `close`) ändern nur Rollen, denen
die Übergabe oder der Mensch das ausdrücklich zuweist.

Aufträge und Projektdokumentation enthalten den aktuellen Stand, keine
Änderungschronik; Historie liegt in Git und `bd history`. Planer ersetzen
überholte Inhalte. Umsetzer ändern weder Auftrag noch Beads-Status: Ergebnis
und Prüfnachweise gehören in Commit/Diff und Commitnachricht; ein fehlender
Commit bleibt ausdrücklich uncommitteter Stand. Einzige Beads-Schreibausnahme
ist `notes` als temporäre Kurzmitteilung (höchstens 600 Zeichen, ersetzen statt
anhängen). Der nächste Handoff-Schritt ersetzt oder leert sie nach Verarbeitung;
Reviewer bilden davor ihr eigenes Urteil. Keine Fortschrittskommentare.
Handoff-Aufträge bleiben kurz; Materialisierungsreview benennt Übergröße,
widersprüchliche Nachträge und nötige Teilung konkret.

## Sitzungsende

Ohne ausdrückliche Anweisung des Menschen weder committen noch pushen noch
Dolt-Remote synchronisieren; ausdrückliche Anweisungen des Menschen oder
Orchestrators gehen vor. Am Ende berichten: geänderte Dateien, Prüfungen,
Beads-Stand und vorgeschlagene nächste Befehle. Ist ein nötiger Sync oder
Push blockiert, den genauen Befehl und den Fehler melden.

## Python und Tests

Python immer über das Projekt-venv starten, nie über `python`/`python3`
im PATH (ein PreToolUse-Hook sperrt das nur in Claude Code; Codex läuft
ohne diese Einschränkung):

```bash
./.venv/bin/python -m pytest    # Testsuite
```

Nicht `./.venv/bin/python -m unittest discover` verwenden: Die Tests sind
pytest-Funktionen (einfache Funktionen und Hypothesis `@given`), keine
`unittest.TestCase`-Klassen; `unittest discover` findet 0 Tests und
endet mit Exit 5, ein falscher Fehlschlag ohne Bezug zu Rechten oder
Zugriff.

## Verbrauchsmessung: Sitzungsdaten sparsam untersuchen

Beim Entwickeln und Prüfen der Tokenmessung keine vollständigen
Roh-Sitzungsdateien in den Agentenkontext laden. Ein deterministischer Parser
darf die Dateien lesen, gibt aber nur gezielt ausgewählte JSON-Metadaten aus
(etwa IDs, Zeitstempel, Modell, Tokenzähler und Kontingentwerte).
Gesprächsinhalte, Prompts, Werkzeugausgaben und Zugangsdaten gehören weder in
die Ausgabe noch in Fehlerdiagnosen. Auch Debug-Ausgaben begrenzen; Kürzungen
und fehlende Messwerte ausdrücklich kennzeichnen. Keine vollständigen
Ereignis-Dumps als Abkürzung verwenden.

Architektur und Messvertrag:
`docs/architecture/tokenmessung-estimatoren.de.md`
(Tokenmessung und Estimatoren).
