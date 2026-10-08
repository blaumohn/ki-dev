---
layout: page
title: Technikleitlinie für ki-dev
permalink: /de/policies/technikleitlinie/
---
<!-- Generiert aus docs/policies/technikleitlinie.de.yaml mit scripts/render-guidelines.py; Änderungen dort vornehmen. -->

Diese projektweite Leitlinie konkretisiert die
[Architektur- und Programmierleitlinien](programmierleitlinie.de.md).
Sie ist bei Planung, Materialisierung, Umsetzung und Review zu berücksichtigen
und gilt für neue und
fachlich geänderte Validierungs- und Prozessgrenzen sowie Abläufe. Bestehende Abweichungen
sind keine Vorbilder; ihre Migration erfolgt im passenden Auftrag, ohne
unbeteiligten Code nebenbei umzubauen.

## Gemeinsame Validierungssprache

- JSON Schema mit der vorhandenen Python-Bibliothek `jsonschema` verwenden;
  im Projekt ist `Draft202012Validator` das bestehende Muster.
- Geprüft werden auch Python-Dictionaries und Listen im Speicher. JSON lesen
  oder schreiben ist dafür keine Voraussetzung; Parsing und Validierung
  bleiben getrennte Schritte.
- Schemata bei der fachlich zuständigen Komponente bündeln und gemeinsame
  Regeln wiederverwenden. Keine zentrale Sammlung unabhängiger Fachschemata
  und keine eigene Validierungs-DSL aufbauen.
- Optionale Felder dürfen fehlen. Vorhandene Werte müssen ihren Vertrag
  erfüllen; `null`, falsche Typen und Leertexte sind nur erlaubt, wenn der
  Vertrag das ausdrücklich vorsieht. Unbekannte Felder je Vertrag behandeln.
- Validierungsfehler an der zuständigen Grenze in bereinigte Diagnosen mit
  Feldpfad übersetzen; keine ungefilterten Validator-Meldungen mit Rohwerten.

**Beispiel:** Ein optionales `handoff` erhält `type: object`; ein enthaltenes
`epic_context` erhält `type: string`, `minLength: 1`, `maxLength: 600` und
das Muster `\S` (mindestens ein Nicht-Leerraumzeichen). Die Grenze wird
einmal im zuständigen Vertrag definiert. `{}` ist als fehlende optionale
Angabe erlaubt, `{"handoff": 7}` wird am Feld `handoff` abgelehnt.

Graphzyklen und andere Beziehungen außerhalb des Schemas prüfen benannte
Funktionen. Das ergänzt die gemeinsame Validierung, ohne deren Typ- und
Feldregeln nochmals zu implementieren.

## Externe Prozesse

- Externe Programme über Plumbum starten. Prozessmechanik gehört an benannte
  I/O-Grenzen; fachlicher Kerncode erhält normalisierte Daten.
- Argumente getrennt übergeben, keine zusammengesetzten Shell-Befehle.
  Arbeitsverzeichnis, Zeitgrenze und erwartete Exitcodes ausdrücklich festlegen.
- Startfehler, Timeout und fehlerhaften Exitstatus sichtbar unterscheiden.
  Prozessausgaben nicht ungefiltert in Diagnosen übernehmen.
- Vorhandene Prozesshelfer nur wiederverwenden, wenn ihre Ein-/Ausgabe- und
  Fehlerverträge passen; keine Kopplung unabhängiger Fachmodule erzwingen.

**Beispiel:** `bd --readonly show BEAD_ID --json` wird am Beads-Adapter über
Plumbum mit getrennten Argumenten, angegebenem Arbeitsverzeichnis und
10 Sekunden Frist gestartet. Der Kern erhält den normalisierten Bead.

## Abläufe als Daten

- Zustände, Übergänge, Wiederholungsgrenzen und Halt stehen in einem
  Ablauf unter `src/ki_dev/flow/*.toml`, nicht in Verzweigungen des
  Ausführers. Eine Schleife ist eine Rückkante mit Wächter und zählender
  Aktion, keine eigene Komponente oder Schicht.
- Der Ausführer implementiert nur benannte Wächter, Aktionen und
  Operationen; `binde` prüft beim Laden, dass Ablauf und Code dasselbe
  Vokabular kennen. Agenten liefern Ereignisse und Laufdaten, wählen aber
  nie selbst eine Kante.
- Inhaltliche Entscheidungen (CHANGES → neue Runde, Rundenlimit,
  Entscheidung des Menschen) gehören in den Ablauf, technische
  (Prozess abgestürzt, Kontextgrenze) in den Ausführer.
- Schichtrichtung: Ablauf kennt weder Ausführer noch Adapter, Adapter
  kennen keinen Ablauf (`tests/test_schichten.py`).

**Beispiel:** „Nach fünf CHANGES hält der Lauf an“ ist der Wächter
`!korrekturrunden_frei` an der Kante `controller_changes` in `delivery.toml`,
nicht ein `if` in der Laufzeit.

## Ausnahmen

Abweichende Werkzeuge benötigen eine konkrete technische Begründung an der
betroffenen Grenze und einen Verweis aus dieser Leitlinie. Bequemlichkeit
oder ein bestehender abweichender Aufruf begründen keine neue Ausnahme.

Bestehende Ausnahme:

- **Pager von `ki-dev session show --pager`** (`session_output.py`):
  Rich `Console.pager()` über `pydoc.pager`, das `$MANPAGER` bzw.
  `$PAGER` über die Shell startet. Technische Begründung: `pydoc`
  bringt die Pagerauswahl (`$MANPAGER`/`$PAGER`, sonst `less` oder
  `more`), die Rückfallebene ohne Terminal und die Behandlung von
  Strg-C ohne verbleibenden Rohmodus des Terminals bereits mit; ein
  eigener Plumbum-Pager würde das nachbauen. `PAGER` ist Konfiguration
  des eigenen Terminals, keine fremde Eingabe. Entscheidung des
  Menschen vom 2026-10-07. Folge: Start- und Exitfehler des Pagers meldet
  die Shell, nicht `ki-dev`; umgeleitete Ausgabe startet keinen Pager.
