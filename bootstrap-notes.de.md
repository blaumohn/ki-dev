# Bootstrap-Entwurf für ki-dev

## 1. Zweck

Dieser Bootstrap ermöglicht, `ki-dev` mit `bd` und Ralphex selbst weiterzuentwickeln, bevor der endgültige `ki-dev`-Orchestrator, die vollständige Zustandsmaschine und die Fachart-Verwaltung implementiert sind.

Der Bootstrap ist ausdrücklich eine vorübergehende Ausführungsschicht.

```text
Zielzustand
= design-notes.de.md bzw. später die daraus hervorgehenden Fachart-Dokumente

Bootstrap
= kleinster Weg, diesen Zielzustand mit vorhandenen Werkzeugen
  schrittweise selbst umzusetzen
```

Der Bootstrap darf den fachlich-architektonischen Zielvertrag nicht neu definieren.

## 2. Was vorhandene Werkzeuge bereits übernehmen

### bd

`bd` übernimmt im Bootstrap bereits:

```text
Vorgänge
Prioritäten
Zustände
Labels
Abhängigkeiten
ready-Ermittlung
Claiming
dauerhafte Arbeitsdaten
```

Der Bootstrap baut deshalb

```text
keinen eigenen Vorgangsgraphen
keine eigene Zyklensuche
keine neue Aufgaben-Datenbank
keinen bd-Fork
```

Beads-Formeln, Moleküle und Gates werden zunächst ebenfalls nicht verwendet. Sie sind für den Bootstrap nicht notwendig und würden vor der eigentlichen `ki-dev`-Zustandsmaschine ein zusätzliches Ablaufmodell einführen.

### Ralphex

Ralphex übernimmt bereits:

```text
Plan-Datei lesen
→ einzelnen Task in frischer Agentensitzung ausführen
→ Validierungsbefehle ausführen
→ Task als erledigt markieren
→ committen
→ nächsten Task in frischer Sitzung ausführen
→ Review
→ Review-Korrekturen
→ Abschluss
```

Der Bootstrap baut deshalb noch keinen eigenen allgemeinen Agentenexecutor.

## 3. Vorläufige Zuordnung zum späteren ki-dev-Vertrag

Der Bootstrap ist nicht die endgültige Zustandsmaschine, verwendet aber soweit sinnvoll dieselben Begriffe:

```text
bd ready
≈ SELECT

bd update <id> --claim
≈ CLAIM

Ralphex-Task
≈ TASK → RESULT

Ralphex-Korrekturrunde
≈ CHANGES

erfolgreicher Task + Validation Commands
≈ PASS_STEP

erfolgreicher abschließender Ralphex-Review
≈ CONTROLLER_FINAL_CHECK → PASS

Fast-forward in den Basisbranch
≈ INTEGRATE

bd close
≈ CLOSE
```

Diese Gleichsetzungen sind nur Bootstrap-Näherungen.

Insbesondere ist ein Ralphex-Review noch kein vollständig implementierter `plan_write_controller`.

Wenn eine notwendige fachliche oder architektonische Entscheidung fehlt, gilt bereits im Bootstrap:

```text
nicht raten
→ NEEDS_DECISION melden
→ Vorgang offen lassen
→ Planning klärt die Entscheidung
→ denselben Bootstrap-Vorgang danach fortsetzen
```

## 4. Bootstrap-Quellen

Bis zur Fachart-Migration gelten als normative Zielquellen:

```text
design-notes.de.md
bootstrap-design-notes.de.md
```

Dabei gilt:

```text
design-notes.de.md
= Zielsystem

bootstrap-design-notes.de.md
= vorübergehender Weg zum Zielsystem
```

Widerspricht eine Bootstrap-Vereinfachung dem Zielsystem, gilt sie ausschließlich für den Bootstrap und verändert den Zielvertrag nicht.

Der Planning-Snapshot dieser laufenden Planning-Sitzung wird getrennt gespeichert.

Er ist für Bootstrap-Stufe 1 bis 3 keine normative Quelle.

Er wird erst nach der Fachart-Migration in Bootstrap-Stufe 4 verarbeitet.

## 5. Bootstrap-Stufe 0 – einmalige manuelle Vorbereitung

Voraussetzung: `bd`, Ralphex, Claude Code und Codex sind bereits installiert und angemeldet.

Im Repository:

```bash
git status --short

bd init
bd setup claude
bd setup codex

bd version
bd ready --json
bd dep cycles

ralphex --version
```

Danach werden genau diese Bootstrap-Artefakte angelegt:

```text
bootstrap-design-notes.de.md

docs/plans/bootstrap-1-materialize.md

bootstrap/
  bd:ki-dev-ablauf-9407
```

`bd:ki-dev-ablauf-9407` enthält beim nächsten `WRITE` nur den seit der letzten erfolgreich geschriebenen Planning-Grenze entstandenen bestätigten Planning-Inhalt, nicht erneut den bereits in `design-notes.de.md` enthaltenen alten Sitzungsverlauf.

Für Bootstrap-Stufe 1 sind keine eigenen Ralphex-Prompts erforderlich.

Die Bootstrap-spezifische Aufgabe und ihre Grenzen stehen im Ralphex-Plan selbst. Die durch `bd setup` erzeugten Agentenanweisungen reichen für den Zugriff auf `bd`.

Alle Bootstrap-Eingaben werden vor dem ersten Ralphex-Lauf committet:

```bash
git add \
  bootstrap-design-notes.de.md \
  bootstrap/ \
  docs/plans/bootstrap-1-materialize.md \
  AGENTS.md CLAUDE.md

git commit -m "bootstrap: prepare first ki-dev materialization"
```

Falls `bd setup` nicht beide Agentendateien verändert, werden nur tatsächlich vorhandene Änderungen committet.

## 6. Bootstrap-Stufe 1 – Planung nach bd materialisieren

Der erste Ralphex-Lauf ist noch nicht selbst durch einen `bd`-Vorgang gestartet.

Er bildet die Brücke:

```text
design-notes.de.md
+
bootstrap-design-notes.de.md
        ↓
Ralphex
        ↓
bd-Vorgänge für die folgenden Bootstrap-Stufen
+
Ralphex-Pläne für diese Vorgänge
```

Er erzeugt mindestens diese Vorgänge:

```text
B2A  Fachart-Schemas umsetzen
     workflow:implementation

B2B  ki-dev check und minimale Nachweisprüfung umsetzen
     workflow:implementation
     depends_on B2A

B3   design-notes.de.md und bootstrap-design-notes.de.md
     in Fachart-Dokumente überführen
     workflow:planning
     depends_on B2B

B4   aktuellen Planning-Snapshot kontrolliert
     in die neuen Fachart-Dokumente einarbeiten
     workflow:planning
     depends_on B3
```

Zusätzlich erzeugt Stufe 1 zu jedem Vorgang eine ausführbare Ralphex-Plan-Datei, die die erzeugte Bead-ID ausdrücklich nennt.

Beispiel:

```text
docs/plans/bd-ab12-bootstrap-schemas.md
docs/plans/bd-cd34-bootstrap-check.md
docs/plans/bd-ef56-bootstrap-fachart-migration.md
docs/plans/bd-gh78-bootstrap-planning-write.md
```

Außerdem entsteht:

```text
bootstrap/materialization-1.md
```

mit

```text
Quellenstand
erzeugte Bead-IDs
Titel
Workflow
Abhängigkeiten
zugehörige Ralphex-Pläne
Abschlussprüfung
```

Der erste Lauf prüft mindestens:

```bash
bd list --json
bd dep cycles
git diff --check
```

und der Review muss zusätzlich den tatsächlichen `bd`-Bestand mit dem Materialisierungsbericht vergleichen.

## 7. Manuelle Schleife ab Bootstrap-Stufe 2

Ab diesem Punkt wird nicht mehr von Hand entschieden, welche Arbeit als Nächstes dran ist.

Der Mensch führt nur noch die vorläufige Dispatcher-Schleife aus:

```bash
bd ready --json

bd update <id> --claim --json

ralphex docs/plans/<plan-fuer-id>.md
```

Nach erfolgreichem Ralphex-Lauf wird dessen Branch in den Ausgangsbranch integriert:

```bash
git switch <basis-branch>
git merge --ff-only <ralphex-branch>
```

Erst danach:

```bash
bd close <id> \
  --reason "Ralphex execution and review passed; branch integrated" \
  --json
```

Dann erneut:

```bash
bd ready --json
```

Damit wird bereits manuell genau die spätere Kernfolge angenähert:

```text
READY
→ CLAIM
→ EXECUTE
→ REVIEW
→ INTEGRATE
→ CLOSE
→ READY
```

## 8. Bootstrap-Stufe 2A – erste Fachart-Schemas

Es wird noch kein Fachart-Graph gebaut.

Fachart-Dokumente sind zunächst Dateien im Repository.

Erste notwendige Facharten:

```text
system_spec
flow_spec
decision
guideline
test_matrix
```

Die kanonischen Daten liegen zunächst beispielsweise unter:

```text
docs/ki-dev/fach/system-spec/
docs/ki-dev/fach/flow-spec/
docs/ki-dev/fach/decision/
docs/ki-dev/fach/guideline/
docs/ki-dev/fach/test-matrix/
```

und die Schemas unter:

```text
schemas/ki-dev/
```

Format der Fachdaten:

```text
YAML
```

Validierung:

```text
JSON Schema
```

Die Schemas prüfen zunächst nur lokale Struktur:

```text
Fachart
Kennung
Titel
Zustand
Pflichtfelder
strukturierte Listen
lokale Unterkennungen
grundlegende Wertebereiche
```

Kein fachlicher Dokumentgraph gehört zu dieser Stufe.

## 9. Bootstrap-Stufe 2B – minimale ki-dev-Prüfschicht

Die erste echte `ki-dev`-Funktion ist:

```bash
ki-dev check
```

Sie wird in Python umgesetzt.

Sie prüft mindestens:

```text
1. alle Fachart-Dateien gegen ihr JSON Schema;

2. doppelte Fachart-Kennungen;

3. ungültige lokale Anforderungskennungen;

4. Verweise einer Testmatrix auf nicht vorhandene
   Spezifikations-/Anforderungskennungen;

5. vorhandene Quelltext- oder Testpfade,
   sofern eine Testmatrix einen konkreten Beleg behauptet.
```

Nicht Teil dieser Stufe:

```text
fachlicher Dokumentgraph
implements-Endpunktregeln
derived_from-Endpunktregeln
allgemeine Graphvalidierung
Zustandsmaschine
Agentenorchestrierung
GitHub-Pages-Renderer
```

### Anforderungs-/Quelltext-Schnittstelle

Spezifikationen dürfen stabile lokale Anforderungen tragen:

```yaml
requirements:
  - id: CW-01
    text: Während WAITING_FOR_DECISION startet kein plan_writer.
    testability: testable
```

Eine Testmatrix darf darauf verweisen:

```yaml
requirement: controlled-write#CW-01
implementation:
  - src/ki_dev/planning.py
tests:
  - tests/test_planning.py::test_waiting_does_not_start_writer
```

`ki-dev check` prüft zunächst die Gültigkeit solcher Verweise.

Es verlangt in dieser Bootstrap-Stufe noch nicht, dass jede prüfbare Anforderung bereits einen Test besitzt. Dadurch kann Planung weiterhin vor Umsetzung stattfinden.

## 10. Bootstrap-Stufe 3 – Migration der großen Entwurfsdokumente

Nach erfolgreicher Stufe 2 gilt:

```text
ki-dev check
```

als Pflichtprüfung für neue Fachart-Dokumente.

Der Planning-Lauf der Stufe 3 liest:

```text
design-notes.de.md
bootstrap-design-notes.de.md
```

und zerlegt deren geltenden Inhalt in die passenden Facharten.

Beispiel:

```text
Definition und Systemaufbau
→ system_spec

CONTROLLED_WRITE-Zustandsablauf
→ flow_spec

„CONTROLLER_FINAL_CHECK ist ein frischer Controller-Lauf“
→ decision

Schreibschnitt-Auflösung
→ guideline

Zustandsmaschinen-Anforderungen ↔ Tests
→ test_matrix
```

Die Migration ist keine wortgetreue Aufteilung nach Überschriften.

Der Agent entscheidet nach fachlicher Bedeutung.

Nach erfolgreicher Migration und Review:

```text
Fachart-Dokumente
= normative Grundlage für weitere Planning-Schreibarbeit

alte *design-notes.de.md
= Migrationsquelle / Archiv
```

Die genaue Archivierungsform wird in diesem Bootstrap nicht vorweggenommen.

## 11. Bootstrap-Stufe 4 – erste strukturierte Planning-Fortschreibung

Erst jetzt wird der bei `WRITE` gespeicherte

```text
bd:ki-dev-ablauf-9407
```

verarbeitet.

Der Lauf prüft:

```text
Planning-Snapshot
+
aktuelle Fachart-Dokumente
```

und schreibt nur die seit der letzten bereits materialisierten Planning-Grenze neu entstandenen Entscheidungen.

Damit wird die zuvor erkannte Verflachungsregel erstmals praktisch benutzt:

```text
bereits geschriebene Planung
→ aus den Fachart-Dokumenten lesen

nur neuer Planning-Nachlauf
→ Snapshot

beides zusammen
→ kontrollierte Fortschreibung
```

Die alte vollständige Planning-Sitzung wird nicht erneut als regulärer Schreibeingang benötigt.

## 12. Zustand nach Bootstrap-Stufe 4

Nach Stufe 4 existieren bereits:

```text
bd
→ Vorgänge, Zustände, Abhängigkeiten, ready

Ralphex
→ autonome Implementierung und Review

Fachart-Schemas
→ strukturierte Planungs-/Entwurfsdokumentation

ki-dev check
→ minimale deterministische Prüfung

Testmatrix-Schnittstelle
→ Anforderung ↔ Quelltext ↔ Test

strukturierte Fachart-Dokumente
→ normative Grundlage der weiteren Planung
```

Noch nicht vorhanden beziehungsweise noch nicht vollständig:

```text
automatischer ki-dev-Dispatcher
vollständiger Planning-Orchestrator
CONTROLLED_WRITE-Zustandsmaschine
persistiertes WAITING_FOR_DECISION
automatisches Resume
Fachart-Graph
vollständige fachliche Graphvalidierung
automatische Fachart-Projektion nach GitHub Pages
```

Ab diesem Zustand kann `ki-dev` selbst mit wesentlich geringerem menschlichem Verwaltungsaufwand weiterentwickelt werden.

## 13. Bootstrap-Abnahmekriterium

Der Bootstrap ist erfolgreich, wenn folgender Ablauf möglich ist:

```text
Planning
→ strukturierte Fachart-Dokumente
→ ki-dev check
→ Planning-Materialisierung nach bd
→ bd ready
→ Ralphex-Umsetzung
→ Review
→ Integration
→ bd close
→ nächste Arbeit
```

und dabei weder ein `bd`-Fork noch eine eigene Graphdatenbank noch eine vollständige `ki-dev`-Zustandsmaschine Voraussetzung sind.

