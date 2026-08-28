# Umsetzungsplan: KI-Dev-Arbeitsweise

## 1. Ergebnis

Es entsteht ein lokales Kommandozeilenwerkzeug namens `ki-dev`. Ein Entwickler
startet es im Wurzelverzeichnis eines Git-Repositories. Es verbindet drei
Bausteine:

1. `bd` speichert Vorgänge, Abhängigkeiten, Prioritäten und Zustände dauerhaft.
2. Ralphex führt freigegebene Implementierungspläne in getrennten Task- und
   Review-Läufen aus, testet, reviewed und committet sie.
3. `ki-dev` wählt genau einen Vorgang aus, weist ihn fest zu und startet den
   richtigen Workflow.

`ki-dev` ist keine zusätzliche Projektmanagement-Datenbank und keine fachliche
Prüfschicht. Fachliche Wahrheit bleibt in der Projektdokumentation; der
Arbeitszustand bleibt in `bd`; Git bleibt die Wahrheit für Quelltext und
Commits.

```text
bd ready
   ↓
ki-dev wählt und bindet genau eine Bead-ID
   ↓
workflow:planning        workflow:implementation
Planer ↔ Benutzer        Ralphex Task-Ausführung
Planungs-Umsetzer        Ralphex Review
Planungs-Reviewer        Tests, Korrekturen, Commit
Doku + bd-Graph
   ↓                         ↓
Vorgang schließen        Vorgang schließen
   ↓
erst jetzt wieder bd ready
```

## 2. Rollen und Arbeitsarten

Es gibt zwei Arbeitsarten, aber mehrere Rollen.

### Planung

Planung ist ein bewusst kleiner, menschlich überprüfbarer Mensch-Planer-Dialog.
Ein ausreichend geklärter Zwischenstand darf während derselben Planning-Sitzung
kontrolliert nach `plan.md` fortgeschrieben werden. Das schließt weder die
Sitzung noch das betreffende Sachthema ab; eine spätere Erkenntnis darf
denselben Sachbereich erneut ergänzen oder korrigieren. Eine solche
Zwischenfortschreibung erzeugt noch keine endgültigen `bd`-Vorgänge,
Untervorgänge oder Abhängigkeiten und bleibt damit klar von der späteren
vollständigen Planning-Materialisierung getrennt.

```text
Planer ↔ Benutzer
→ ausreichend geklärter Zwischenstand
→ kontrollierte Planfortschreibung in plan.md (CONTROLLED_WRITE)
→ zurück in denselben Mensch-Planer-Dialog
...
→ Gesamtplan ausreichend fertig
→ menschliche Freigabe des Gesamtplans
→ vollständige Planning-Materialisierung (MATERIALIZE)
→ Planungs-Umsetzer: Projektdokumentation sowie bd-Vorgänge,
  Untervorgänge und Abhängigkeiten
→ Planungs-Reviewer
→ bei Mängeln zurück zum Planungs-Umsetzer
→ Planning-Vorgang schließen
```

- Der Planer versteht Problem, Quellen und Optionen und führt den Dialog mit
  dem Benutzer. Seine Ausgaben bleiben klein genug, dass der Benutzer sie
  vollständig prüfen kann.
- Der Planungs-Umsetzer wird erst nach der menschlichen Freigabe des ausreichend
  fertigen Gesamtplans tätig (`MATERIALIZE`). Er überführt diesen freigegebenen
  Gesamtplan in die erforderliche konsistente Projektdokumentation und erzeugt
  die nötigen `bd`-Vorgänge, Untervorgänge und Abhängigkeiten. Der freigegebene
  Plan ist dabei zunächst ein Laufartefakt, keine Vorgabe für ein neues Dokument:
  Er entscheidet anhand des Plans und der vorhandenen Repository-Struktur, welche
  bestehende Planungs- oder Architekturdokumentation tatsächlich geändert werden
  muss.
- Der Planungs-Reviewer vergleicht freigegebenen Plan, tatsächliche Doku und
  tatsächlichen `bd`-Graphen.
- Der Benutzer entscheidet fachliche oder architektonische Fragen, bestätigt im
  Planungsdialog die Zwischenstände der kontrollierten Planfortschreibung und
  gibt am Ende den ausreichend fertigen Gesamtplan für die Materialisierung frei.

### Kontrollierte Planfortschreibung: Freigabe und Snapshot

Eine kontrollierte Planfortschreibung arbeitet nicht auf dem fortlaufend
veränderlichen Gespräch, sondern auf einem eingefrorenen **Snapshot** des dafür
freigegebenen Planning-Kontexts. Die Planning-Sitzung darf während der Kontroll-
und Schreibschleife weiterlaufen; die konkrete Schreibschleife bleibt trotzdem
an ihren unveränderlichen Eingang gebunden.

Für V1 kann als zu prüfendes einfaches Modell die Folge der Planerausgaben der
bewusst kleinen Planning-Sitzung als Planning-Kontext dieses Snapshots dienen.
Der Schreibkontroller erhält diesen gesamten Kontext, nicht nur die letzte
Entscheidung, und muss weiterhin geltende frühere Entscheidungen berücksichtigen,
damit die Fortschreibung keine Regression erzeugt.

Ausgelöst wird eine Fortschreibung durch eine menschliche `WRITE`-Eingabe im
Planungsdialog:

- Enthält die `WRITE`-Eingabe **keinen neuen Planungsinhalt**, sondern nur
  Zustimmung oder Freigabe, gilt die unmittelbar vorherige Planerausgabe als
  bestätigt und der Snapshot wird daraus erzeugt.
- Enthält die `WRITE`-Eingabe **neuen Planungsinhalt**, gelangt dieser nicht
  unmittelbar in den Snapshot. Der Planer muss ihn zuerst in einer weiteren
  sichtbaren Planerausgabe verarbeiten; erst nach menschlicher Bestätigung
  dieser Ausgabe wird der Snapshot erzeugt.

Dadurch bleiben zwei Prüfungen getrennt:

1. Der Mensch prüft, ob der Planer den Dialogstand richtig erfasst hat.
2. Der Schreibkontroller prüft auf dem Snapshot, ob der bestätigte Stand für die
   konkrete Schreibarbeit an `plan.md` ausreichend bestimmt ist.

Fehlt für die verlangte Fortschreibung eine notwendige fachliche oder
architektonische Entscheidung, darf der Schreibkontroller sie nicht selbst
treffen; die Runde eskaliert zurück zu Planning. Nach der Klärung kann aus dem
normalen menschlich geprüften Planning-Dialog erneut eine Freigabe entstehen;
eine automatische neue `WRITE`-Eingabe entsteht dadurch nicht.

Der Snapshot ist ein reiner Schreibeingang für `plan.md`. Er erzeugt keine
`bd`-Vorgänge, Untervorgänge oder Abhängigkeiten; diese entstehen weiterhin
ausschließlich in der späteren vollständigen Planning-Materialisierung
(`MATERIALIZE`).

### CONTROLLED_WRITE: Lebenszyklus und rekonstruierbarer Laufzustand

Die konkrete Kontroll- und Schreibschleife auf einem Snapshot heißt
`CONTROLLED_WRITE`. Der Schreibkontroller (`plan_write_controller`) ist dafür
ein eigener nicht-interaktiver Agentenlauf mit Profil `control`; der Schreibagent
(`plan_writer`) läuft mit Profil `work`.

Ein `CONTROLLED_WRITE` besitzt über alle seine Schreibschnitte und
Korrekturschleifen hinweg einen logisch zusammenhängenden Kontroller-Zustand.
Der Schreibkontroller prüft am Snapshot, ob der freigegebene Planning-Stand
fachlich und architektonisch ausreichend bestimmt ist. Den konkreten begrenzten
Schreibauftrag bestimmt er dagegen nicht aus dem Snapshot allein, sondern
zugleich aus dem aktuellen geprüften Stand von `plan.md`; bei weiteren
Schreibschnitten kommen die bisherigen `CONTROLLED_WRITE`-Ergebnisse hinzu:

```text
gespeicherter Planning-Snapshot
        +
aktuelles geprüftes plan.md
        +
bei späteren Schritten: bisherige CONTROLLED_WRITE-Ergebnisse
        ↓
plan_write_controller
        ↓
nächster begrenzter TASK
```

So bestimmt der Schreibkontroller den ersten begrenzten `TASK` und ebenso jeden
weiteren nach `PASS_STEP`; das vermeidet Regressionen sowie bereits erledigte
oder unnötige Änderungen. Für jeden neuen Schreibschnitt startet ein frischer
`plan_writer`. Innerhalb desselben Schreibschnitts bleibt bei normalen
`CHANGES` derselbe Schreibagent zuständig:

```text
TASK
→ Schreibagent
→ RESULT
→ Schreibkontroller
   ├─ CHANGES   → derselbe Schreibagent
   └─ PASS_STEP → Schreibschnitt beendet
```

Erst nach `PASS_STEP` bestimmt der Schreibkontroller den nächsten begrenzten
Schreibauftrag; dafür startet ein frischer `plan_writer`. Sind keine weiteren
Schreibaufträge nötig, ist der `CONTROLLED_WRITE` abgeschlossen und der
Planungsdialog läuft weiter. Fehlt eine notwendige fachliche oder
architektonische Entscheidung, eskaliert der Schreibkontroller zurück zu
Planning, statt sie selbst zu treffen.

Die Korrektheit von `CONTROLLED_WRITE` hängt nicht von einer
executor-spezifischen Sitzungsfortsetzung ab; ein technischer Session-Fork ist
keine Architekturvoraussetzung. Der für eine Fortsetzung nötige
Kontroller-Zustand ist rekonstruierbar aus

- dem gespeicherten freigegebenen Planning-Snapshot,
- dem aktuellen geprüften Planungsdokument und
- den bisherigen Ergebnissen des laufenden `CONTROLLED_WRITE`.

### Session-Handoff: Fortsetzung in einer neuen Planning-Sitzung

`SESSION_HANDOFF` ist eine eigene persistierte Orchestrator-Phase desselben
bereits laufenden Planning-Workflows und derselben Planning-Bead. Er ist kein
eigener `bd`-Vorgang und kein neuer fachlicher Planning-Vorgang; er erzeugt
keine neue Planning-Bead. Er ist außerdem weder die kontrollierte
Planfortschreibung nach `plan.md` noch die vollständige Planning-Materialisierung
(`MATERIALIZE`). Die kontrollierte Planfortschreibung sichert einen
Zwischenstand in `plan.md`; die Materialisierung überträgt den freigegebenen
Gesamtplan in die Projektdokumentation und den `bd`-Graphen; der
`SESSION_HANDOFF` verschiebt nur die weitere Denkarbeit in eine neue
Planning-Sitzung. Während des Handoffs gilt `state.json.phase = SESSION_HANDOFF`,
sodass ein Abbruch bzw. `resume` eindeutig an dieser Phase desselben Laufs
anknüpft.

Relevant wird er erst, wenn der Mensch oder eine unterstützende
Größenbegrenzung erkennt, dass die laufende Planning-Sitzung für weiteres
zuverlässiges Denken zu groß geworden ist. Er erfolgt nicht zwingend nach einer
festen Anzahl von Turns; eine konkrete feste Größen-, Token- oder Turn-Schwelle
ist nicht beschlossen. Ein unterstützendes Größenbegrenzungssignal bleibt
ausdrücklich zulässig.

Zweck ist ausschließlich, das Planning in einer neuen Planning-Sitzung
fortsetzen zu können. Das Sachthema wird dadurch nicht abgeschlossen; eine
spätere Erkenntnis darf denselben Sachbereich weiter ergänzen oder korrigieren.

Ein technischer Session-Fork, ein Klon oder eine executor-spezifische
Sitzungsfortsetzung ist keine Architekturvoraussetzung. Der `SESSION_HANDOFF`
wird von einer eigenen nicht-interaktiven Agentenrolle `session_handoff` mit
Profil `control` ausgeführt. Ihre Aufgabe ist ausschließlich, den bisherigen
Planning-Kontext chronologisch auszuwerten und daraus die Fortsetzungsübergabe
für eine neue Planning-Sitzung zu erzeugen. Das Rohtranskript **kann** als
Rückfallquelle erhalten bleiben; seine Aufbewahrung ist keine Pflicht des
Kernvertrags.

Ein `SESSION_HANDOFF` erzeugt keine endgültigen `bd`-Vorgänge, Untervorgänge
oder Abhängigkeiten. Die neue Planning-Sitzung setzt das Planning auf Grundlage
der Übergabe fort; spätere kontrollierte Planfortschreibungen und die spätere
vollständige Planning-Materialisierung bleiben davon unabhängige Vorgänge.

### Vollständige Planning-Materialisierung (MATERIALIZE)

`MATERIALIZE` ist ein eigener Vorgang und weder `CONTROLLED_WRITE` noch
`SESSION_HANDOFF`. Er beginnt erst, wenn der Gesamtplan ausreichend fertig und
vom Menschen freigegeben ist. „Bereit für eine kontrollierte Planfortschreibung“
bedeutet ausdrücklich nicht „bereit für `MATERIALIZE`“.

`MATERIALIZE` überführt den freigegebenen Gesamtplan in die erforderliche
konsistente Projektdokumentation und in konkrete `bd`-Umsetzungsarbeit. Dabei
entstehen – anders als bei `CONTROLLED_WRITE` und `SESSION_HANDOFF` – die
nötigen `bd`-Vorgänge, Untervorgänge und Abhängigkeiten. Anschließend prüft der
bestehende Planungs-Reviewer das Ergebnis gegen freigegebenen Plan, tatsächliche
Doku und tatsächlichen `bd`-Graphen; bei Mängeln geht es zurück an den
Planungs-Umsetzer.

Vor der menschlichen Freigabe des Gesamtplans wird nichts materialisiert. Die
während der Sitzung nach `plan.md` fortgeschriebenen Zwischenstände ersetzen
diese Freigabe nicht; `MATERIALIZE` beginnt erst nach ihr.

### Umsetzung

```text
Ralphex Task-Ausführung
→ Tests
→ Ralphex Review
→ Korrekturen
→ abschließende Prüfung
→ Commit
```

`ki-dev` erzeugt dafür aus genau einem `bd`-Vorgang einen ausführbaren
Ralphex-Plan, startet Task-Ausführung und Review getrennt auf demselben
Arbeitszweig und übernimmt anschließend Integration und Zustandswechsel.

### Orchestrator

Der Orchestrator ist deterministisch und trifft keine Fachentscheidungen. Er
erzwingt Auswahl, Rollenfolge, Schreibgrenzen, Wiederholungen, Zustandswechsel
und Abbruchbedingungen.

Leitregel:

```text
Prompt:
Denken, Interpretation, Qualitätsurteil und Formulierung

Orchestrator:
Ablauf, aktuelle Bead-ID, Schreibrechte, Zustände, Gates,
Wiederholungsgrenzen, Commit-/Integrationsprüfung und close
```

## 3. Öffentliche Befehlsoberfläche

Die erste nutzbare Version bietet diese Befehle:

| Befehl | Wirkung |
| --- | --- |
| `ki-dev init` | Repository für `bd`, Ralphex und `ki-dev` einrichten |
| `ki-dev doctor` | Versionen, Anmeldung, Git-Zustand und Konfiguration prüfen |
| `ki-dev plan "<Ziel>"` | vollständigen Planning-Workflow erstellen und ausführen: Planning-Bead, interaktiver Planer, Benutzerfreigabe, Materialisierung, Review und `bd`-Graph |
| `ki-dev ready` | ausführbare Arbeit aus `bd` in menschlich lesbarer Form anzeigen |
| `ki-dev run [<id>]` | einen expliziten oder den nächsten ready-Vorgang ausführen |
| `ki-dev run --loop` | Vorgänge nacheinander ausführen, bis nichts ready ist oder ein Gate stoppt |
| `ki-dev status` | aktiven Lauf, Phase, Bead, Branch und nächste Aktion anzeigen |
| `ki-dev resume [<id>]` | unterbrochenen oder eskalierten Lauf an seiner gespeicherten Phase fortsetzen |
| `ki-dev logs [<id>]` | Orchestrator- und Ralphex-Protokoll eines Laufs anzeigen |

`Ctrl-C` stoppt den gestarteten Kindprozess kontrolliert. Der Vorgang wird
nicht geschlossen; `ki-dev status` zeigt danach `ki-dev resume` als nächste
Aktion.

Nicht Teil der ersten Version sind ein Web-UI, parallele Ausführung, Push,
Pull-Request-Erstellung, Deployment und ein allgemeiner Workflow-Designer.

## 4. Einrichtung und erste Verwendung

### 4.1 Voraussetzungen installieren

Die dokumentierte macOS-Referenzstrecke lautet:

```bash
brew install beads

mkdir -p ~/.local/bin
curl -fsSL \
  https://raw.githubusercontent.com/umputun/ralphex/master/scripts/ralphex-dk.sh \
  -o ~/.local/bin/ralphex
chmod +x ~/.local/bin/ralphex
```

`~/.local/bin` muss im `PATH` liegen. Der Ralphex-Wrapper benötigt eine laufende
Docker-Installation. Zusätzlich müssen Claude Code und Codex für die in den
Rollen referenzierten Executor-Arten angemeldet sein; deren lokale
Anmeldedaten werden vom Wrapper in den Container übernommen.

Für die Entwicklung dieses Repositories soll es nach dem ersten Scaffold diese
Befehle geben:

```bash
make build
./bin/ki-dev --help
make test
make install
```

Ein Release soll später ein einzelnes `ki-dev`-Binary bereitstellen. Ein
Homebrew-Tap ist erst nach dem ersten stabilen Release erforderlich.

### 4.2 Zielprojekt initialisieren

```bash
cd /pfad/zum/projekt
ki-dev init
ki-dev doctor
```

`ki-dev init` ist idempotent und führt nachvollziehbar aus:

1. Git-Repository und Wurzelverzeichnis erkennen.
2. Vorhandene Konfiguration feststellen und geplante Änderungen anzeigen.
3. Falls nötig `bd init --quiet` ausführen.
4. Die passende Agentenintegration von `bd` einrichten.
5. Falls nötig `ralphex --init` ausführen.
6. `.ki-dev/config.toml` mit Modellprofilen, Rollenzuordnung und optionalen
   Rollen-Overrides, lokale Prompts und Laufverzeichnisse anlegen.
7. Ralphex so konfigurieren, dass `ki-dev` den Lebenszyklus der generierten
   Ein-Vorgang-Pläne verwaltet.
8. Einen klar abgegrenzten Agentenvertrag in die vorhandene Agentendokumentation
   einfügen oder aktualisieren.
9. Abschließend automatisch `ki-dev doctor` ausführen.

Globale Abhängigkeiten installiert `ki-dev init` nicht stillschweigend. Fehlt
etwas, nennt es den genauen Installations- oder Anmeldebefehl und beendet sich
ohne halbfertigen Lauf.

Zielstruktur im Projekt:

```text
.beads/                     dauerhafter bd-Arbeitsgraph
.ralphex/                   projektspezifische Ralphex-Konfiguration
.ki-dev/config.toml         deterministische ki-dev-Konfiguration
.ki-dev/prompts/            Rollenverträge
.ki-dev/runs/               lokale Laufzustände und generierte Pläne
AGENTS.md oder CLAUDE.md    kurzer, verwalteter Agentenvertrag
```

Laufdateien und temporäre Ralphex-Pläne werden ignoriert. Konfiguration und
bewusst angepasste Prompts werden versioniert.

### 4.3 Was `doctor` beweist

`ki-dev doctor` prüft mindestens:

- unterstützte Versionen von `bd`, Ralphex, Git und aller referenzierten
  Executor;
- erfolgreiche Anmeldung für jeden über Modellprofile und Rollen-Overrides
  referenzierten Executor, soweit die jeweilige CLI dies lokal prüfen kann;
- vorhandenes `bd`-Repository und lesbares JSON von `bd ready --json`;
- gültige Ralphex-Konfiguration und erreichbaren Executor;
- eindeutige Projektwurzel und beschreibbare Laufverzeichnisse;
- keinen widersprüchlichen aktiven `ki-dev`-Lauf;
- konfigurierte Schreibgrenzen und vorhandene Promptdateien;
- jedes verwendete Modellprofil existiert;
- Profil und Rollen-Override ergeben eine vollständige und verfügbare
  Executor-/Modell-/Effort-Zuordnung;
- die beschlossenen echten Umsetzer-/Reviewer-Paare (Planungs-Umsetzer/
  Planungs-Reviewer sowie Implementierer/Implementation-Reviewer) verwenden
  jeweils verschiedene Executor; für `plan_write_controller` und `plan_writer`
  (`CONTROLLED_WRITE`) wird keine Executor-Trennung verlangt.

Die Ausgabe endet mit einer eindeutigen nächsten Aktion:

```text
READY: ki-dev plan "<Ziel>"
```

oder beispielsweise:

```text
NOT READY: Ralphex fehlt
Installieren: siehe Abschnitt 4.1
Danach:       ki-dev doctor
```

## 5. Dev-User-UX-Story

### 5.1 Neue Arbeit planen

Der Entwickler startet nur mit einem Ziel:

```bash
ki-dev plan "VPS-Service mit reproduzierbarem Deployment"
```

`ki-dev` erzeugt intern einen normalen `bd`-Task mit einem Workflow-Label:

```bash
bd create \
  "VPS-Service mit reproduzierbarem Deployment planen" \
  -t task \
  -p 2 \
  --labels workflow:planning \
  --json
bd update <planning-id> --claim --json
```

`planning` wird zunächst als Label und nicht als eigener `bd`-Typ modelliert.
Damit bleibt die Integration mit den dokumentierten Standardtypen von `bd`
portabel.

Danach beginnt im selben Terminal die starke interaktive Planung. Der Dialog
bleibt bewusst klein: Jede Planerausgabe bleibt so kurz, dass der Benutzer sie
vollständig prüfen kann.

```text
ki-dev: Planning bd-a1b2
Planer: Welche Betriebsumgebung und welche Ausfallgrenze gelten?
Benutzer: ...
Planer: Ich empfehle Variante B, weil ...
Benutzer: Einverstanden, bitte so festhalten.
ki-dev: WRITE ohne neuen Inhalt, vorherige Planerausgabe bestätigt
        Snapshot erzeugt, Zwischenstand kontrolliert nach plan.md fortgeschrieben
        Planning-Sitzung läuft weiter
Planer: Offen ist noch das Secrets-Handling ...
...
Planer: Zusammenfassung der getroffenen Entscheidungen ...
Gesamtplan freigeben und materialisieren? [y/N]
```

Ein ausreichend geklärter Zwischenstand darf dabei nach `plan.md`
fortgeschrieben werden, ohne die Planning-Sitzung zu beenden. Die Freigabe mit
`y` gilt dagegen der vollständigen Planning-Materialisierung. Vor `y` wird
nichts materialisiert. Nach der Freigabe:

1. speichert `ki-dev` den freigegebenen Plan als Übergabeartefakt des Laufs;
2. startet es den Planungs-Umsetzer;
3. dieser bestimmt aus Plan und vorhandener Repository-Struktur, ob und welche
   bestehende Planungs- oder Architekturdokumentation geändert werden muss,
   und erzeugt die Implementation-Vorgänge mit ihren Untervorgängen und
   Abhängigkeiten;
4. alle erzeugten Wurzelvorgänge hängen zunächst vom Planning-Vorgang ab und
   können deshalb noch nicht versehentlich anlaufen;
5. der Planungs-Reviewer vergleicht Plan, Doku und `bd`-Graph;
6. bei `CHANGES` geht es automatisch zurück zum Planungs-Umsetzer;
7. bei `ESCALATE` stoppt der Lauf mit einer konkreten Frage;
8. bei `PASS` werden die Dokuänderungen integriert und der Planning-Vorgang
   geschlossen.

Die typischen internen `bd`-Operationen sind:

```bash
bd create "VPS-Grundstruktur umsetzen" \
  -t task --labels workflow:implementation --json
bd create "VPS-Deployment umsetzen" \
  -t task --labels workflow:implementation --json
bd create "VPS-E2E-Test ergänzen" \
  -t task --labels workflow:implementation --json

bd dep add <deployment-id> <grundstruktur-id>
bd dep add <e2e-id> <deployment-id>
bd dep add <grundstruktur-id> <planning-id>
```

Nach Erfolg sieht der Entwickler nur die Zusammenfassung:

```text
PASS bd-a1b2
Dokumentation: docs/architecture/vps.md
Neue Vorgänge: bd-b200, bd-b201, bd-b202
Planning-Vorgang geschlossen
Nächste Aktion: ki-dev ready
```

### 5.2 Geplante Arbeit ausführen

```bash
ki-dev ready
```

zeigt beispielsweise:

```text
READY
bd-b200  P2  implementation  VPS-Grundstruktur umsetzen
```

Ein einzelner kontrollierter Lauf:

```bash
ki-dev run bd-b200
```

Oder der autonome Arbeitsmodus:

```bash
ki-dev run --loop
```

Die interne Reihenfolge für jeden Vorgang ist fest. Für Implementation ist der
erzeugte Ein-Vorgang-Plan ein Ralphex-Ausführungsplan; er ist ausdrücklich
nicht die Ralphex-eigene Planungsphase (`ralphex --plan`). Diese wird im
normalen `ki-dev`-Ablauf nicht verwendet:

```text
bd ready --json
→ Kandidat deterministisch auswählen
→ Bereitschaft erneut prüfen und atomar claimen
→ ID in .ki-dev/runs festschreiben
→ bd show <id> --json
→ Workflow-Label lesen
→ Ein-Vorgang-Ralphex-Plan erzeugen
→ Ralphex `--tasks-only` in isoliertem Worktree/Branch mit dem `work`-Profil starten
→ Ausführungsnachweis prüfen
→ Ralphex `--review` im selben Worktree gegen gespeicherten base_commit mit dem `control`-Profil starten
→ Kontroll-Ausführungsnachweis prüfen
→ Ergebnis per Fast-forward in den Ausgangsbranch integrieren
→ Commit und sauberer Arbeitsbaum prüfen
→ bd close <id> --reason "..." --json
→ erst danach erneut bd ready --json
```

Der erzeugte Ralphex-Plan enthält genau einen `bd`-Vorgang:

```markdown
# Plan: bd-b200 VPS-Grundstruktur umsetzen

## Context
Vollständige Beschreibung und maßgebliche Quellen aus bd-b200.

## Validation Commands
- `gezielter-testbefehl`
- `notwendiger-gesamtbefehl`

### Task 1: bd-b200 VPS-Grundstruktur umsetzen
- [ ] Akzeptanzkriterium 1
- [ ] Akzeptanzkriterium 2
```

Die folgenden Aufrufe zeigen die aus der Beispielkonfiguration aufgelösten
Parameter; der Adapter verdrahtet Modell- oder Effort-Werte nicht, sondern
leitet sie aus Konfiguration und Overrides ab:

```bash
ralphex \
  --tasks-only \
  --task-model=sonnet:high \
  --worktree \
  --branch=ki-dev/bd-b200 \
  .ki-dev/ralphex/plans/bd-b200.md

ralphex \
  --codex \
  --review \
  --review-model=sol:high \
  --base-ref=<base_commit> \
  .ki-dev/ralphex/plans/bd-b200.md
```

Die genaue Flag-Kompatibilität wird gegen die im Projekt unterstützte
Ralphex-Version getestet und in `ki-dev doctor` abgesichert. `ki-dev` pusht
nichts. Der Review-Lauf startet im vom Task-Lauf erzeugten Worktree und nutzt
den für den Lauf gespeicherten `base_commit`. Nach beiden erfolgreichen Läufen
wird nur per Fast-forward integriert. Ist das nicht möglich, bleibt der
Vorgang offen und der Benutzer erhält eine konkrete Integrations-Eskalation.

### 5.3 Unterbrechung oder Eskalation

Beispiel:

```text
ESCALATE bd-b200
Phase: REVIEW
Grund: Die Quellen legen nicht fest, ob fehlende Secrets Start oder Deploy
       blockieren sollen.
Nächste Aktion: ki-dev resume bd-b200
```

Der Benutzer ergänzt die Entscheidung in der maßgeblichen Dokumentation oder
beantwortet sie im fortgesetzten Planning-Gate und führt aus:

```bash
ki-dev resume bd-b200
```

`resume` liest nicht erneut `bd ready`. Es verwendet dieselbe Bead-ID, denselben
Lauf und die gespeicherte Phase.

## 6. Dauerhaftes Daten- und Zustandsmodell

### `bd` bleibt die Arbeitswahrheit

Die erste Version verwendet normale `bd`-Typen und Workflow-Labels:

```text
type: task | bug | feature | epic | decision
label: workflow:planning | workflow:implementation
```

Fehlt ein Workflow-Label, gilt ein ausführbarer Bug, Task oder Feature-Vorgang
als `workflow:implementation`. Mehrere widersprüchliche Workflow-Labels sind ein
Konfigurationsfehler und werden nicht geraten.

Jeder Implementation-Vorgang soll enthalten:

```text
Ziel
Maßgebliche Quellen
Umfang
Nicht Teil dieses Vorgangs
Akzeptanzkriterien
Prüfbefehle
Reviewer prüft besonders
Eskalation wenn
```

### Lokaler Laufzustand ist klein

`.ki-dev/runs/<run-id>/state.json` speichert nur Orchestrierungszustand:

```text
run_id
bead_id
workflow
phase
role
attempt
base_branch und base_commit
work_branch
ralphex_plan und progress_log
configured_executor und configured_model
configured_effort
observed_executor und observed_model
observed_effort
letztes Ergebnis
```

Für einen laufenden `CONTROLLED_WRITE` bleibt der Kontroller-Zustand über alle
Schreibschnitte und Korrekturschleifen hinweg zusammenhängend. Der vollständige
logische Kontroller-Zustand ist ohne executor-spezifische Sitzungsfortsetzung
rekonstruierbar aus

```text
gespeicherter freigegebener Planning-Snapshot
+ aktuelles geprüftes plan.md
+ bisherige Ergebnisse des laufenden CONTROLLED_WRITE
```

Planning-Snapshot und bisherige `CONTROLLED_WRITE`-Ergebnisse sind dafür
gespeicherte Laufartefakte bzw. Laufdaten; ob sie in einer oder mehreren Dateien
und unter welchem Namen abgelegt werden, legt dieser Plan nicht fest.

Davon getrennt bleibt `state.json` der kleine persistierte
Orchestrierungszustand, der die Wiederaufnahme des Laufs ermöglicht. Bei
Wiederaufnahme muss der Orchestrator daraus eindeutig erkennen, in welcher Phase
und gegebenenfalls welchem aktiven Schreibschnitt der Lauf steht und ob für
`CHANGES` derselbe `plan_writer` wiederzuverwenden ist. Wie diese Bezüge
innerhalb des bestehenden Laufzustands technisch dargestellt werden, legt dieser
Plan hier nicht fest. Innerhalb eines Schreibschnitts übernimmt bei `CHANGES`
derselbe `plan_writer` erneut; jeder neue Schreibschnitt beginnt mit einem
frischen `plan_writer`.

Während eines `SESSION_HANDOFF` ist im selben `state.json` desselben Laufs
`phase = SESSION_HANDOFF` persistiert. Dadurch bleibt eine Wiederaufnahme über
`ki-dev resume` eindeutig an dieser Phase möglich. Dafür entsteht keine neue
Zustandsdatei und kein neues Schema; es genügt das bereits vorhandene Feld
`phase`.

Taskbeschreibung und Status werden nicht dupliziert; sie werden aus `bd`
gelesen. Fachentscheidungen werden nicht nur im Laufzustand aufbewahrt: Ein
ausreichend geklärter Zwischenstand kann bereits während `PLAN_INTERACTIVE`
kontrolliert nach `plan.md` fortgeschrieben werden; erst die spätere
vollständige Planning-Materialisierung überträgt den ausreichend fertigen und
freigegebenen Gesamtplan in die vorgesehene Projektdokumentation und den
`bd`-Graphen.

Pro Repository darf die erste Version nur einen schreibenden Lauf gleichzeitig
haben. Eine atomare Lockdatei verhindert einen zweiten Orchestrator.

## 7. Deterministische Zustandsautomaten

### Dispatcher

```text
IDLE
→ SELECT
→ CLAIM
→ DISPATCH
   ├─ workflow:planning       → PLAN_INTERACTIVE
   └─ workflow:implementation → IMPLEMENT_PREPARE
→ CLOSE
→ IDLE oder SELECT bei --loop
```

Nach `CLAIM` bleibt die Bead-ID unveränderlich. Während eines laufenden
Workflows darf `bd ready` nur zur Anzeige, niemals zur Neuauswahl verwendet
werden.

### Planning-Workflow

```text
PLAN_INTERACTIVE
   ├─ WRITE ohne neuen Planungsinhalt
   │     → vorherige Planerausgabe bestätigt → Snapshot
   ├─ WRITE mit neuem Planungsinhalt
   │     → weitere sichtbare Planerausgabe → menschliche Bestätigung → Snapshot
   ├─ Snapshot → CONTROLLED_WRITE
   │     Schreibkontroller prüft Snapshot auf ausreichende Bestimmtheit
   │     ├─ Entscheidung fehlt → Eskalation zurück zu Planning → PLAN_INTERACTIVE
   │     └─ ausreichend bestimmt → Schreibkontroller bestimmt begrenzten TASK
   │           aus Snapshot + geprüftem plan.md (+ bisherige CONTROLLED_WRITE-Ergebnisse)
   │           → frischer plan_writer → RESULT → Schreibkontroller
   │              ├─ CHANGES          → derselbe plan_writer
   │              ├─ Entscheidung fehlt → Eskalation zurück zu Planning → PLAN_INTERACTIVE
   │              └─ PASS_STEP         → Schreibschnitt beendet
   │                    ├─ nächster TASK nötig → frischer plan_writer
   │                    └─ CONTROLLED_WRITE abgeschlossen → PLAN_INTERACTIVE
   ├─ Mensch oder unterstützendes Größenbegrenzungssignal erkennt zu große Sitzung
   │     → SESSION_HANDOFF (persistierte Phase, state.json.phase = SESSION_HANDOFF)
   │       → neue Planning-Sitzung → PLAN_INTERACTIVE
   └─ Plan ausreichend fertig → HUMAN_APPROVAL
HUMAN_APPROVAL
→ MATERIALIZE
→ REVIEW
   ├─ PASS     → INTEGRATE → CLOSE
   ├─ CHANGES  → MATERIALIZE
   └─ ESCALATE → PAUSED
```

Die kontrollierte Planfortschreibung (`CONTROLLED_WRITE`) bleibt innerhalb von
`PLAN_INTERACTIVE` und schreibt nur `plan.md`. Sie arbeitet auf einem
eingefrorenen Snapshot des freigegebenen Planning-Kontexts (Abschnitt 2) und
wird durch eine menschliche `WRITE`-Eingabe ausgelöst. Neuer Planungsinhalt in
dieser Eingabe muss der Planer erst in einer vom Menschen bestätigten Ausgabe
verarbeiten, bevor der Snapshot entsteht. Der Schreibkontroller
(`plan_write_controller`) prüft danach den Snapshot auf ausreichende
Bestimmtheit und eskaliert bei fehlender fachlicher oder architektonischer
Entscheidung zurück in den Planungsdialog, ohne sie selbst zu treffen.

Ein `CONTROLLED_WRITE` hält über alle Schreibschnitte und `CHANGES`-Schleifen
hinweg einen zusammenhängenden Kontroller-Zustand (Abschnitt 2). Die Prüfung auf
ausreichende Bestimmtheit bleibt auf den Snapshot bezogen; den begrenzten `TASK`
je Schreibschnitt bestimmt der Schreibkontroller dagegen aus dem Snapshot und
dem aktuellen geprüften `plan.md`, bei weiteren Schreibschnitten zusätzlich aus
den bisherigen `CONTROLLED_WRITE`-Ergebnissen. Dafür startet ein frischer
`plan_writer`. Innerhalb eines Schreibschnitts übernimmt bei `CHANGES` derselbe
`plan_writer`; erst nach `PASS_STEP` bestimmt der Schreibkontroller den nächsten
`TASK` oder schließt den `CONTROLLED_WRITE` ab.
Der Kontroller-Zustand ist ohne executor-spezifische Sitzungsfortsetzung aus
Snapshot, aktuellem geprüften `plan.md` und den bisherigen Schreibschnitt-
Ergebnissen rekonstruierbar. Endgültige `bd`-Vorgänge, Untervorgänge und
Abhängigkeiten entstehen erst in `MATERIALIZE`.

`SESSION_HANDOFF` (Abschnitt 2) ist selbst eine echte persistierte
Orchestrator-Phase desselben Planning-Workflows und derselben Planning-Bead,
kein eigener `bd`-Vorgang und kein neuer fachlicher Planning-Vorgang. Aus
`PLAN_INTERACTIVE` kann bei angefordertem Handoff in die persistierte Phase
`SESSION_HANDOFF` gewechselt werden; nach erfolgreichem Handoff wechselt der
Workflow mit einer neuen Planning-Sitzung zurück nach `PLAN_INTERACTIVE`. Der
Wechsel in diese Phase erfolgt, wenn der Mensch oder ein unterstützendes
Größenbegrenzungssignal erkennt, dass die laufende Planning-Sitzung für
zuverlässiges weiteres Denken zu groß geworden ist; eine feste Größen-, Token-
oder Turn-Schwelle legt dieser Plan dafür nicht fest. Solange diese Phase läuft,
ist `state.json.phase = SESSION_HANDOFF` persistiert, sodass ein Abbruch bzw.
`resume` eindeutig hier wieder anknüpft. Die Rolle `session_handoff` erzeugt eine
Fortsetzungsübergabe; das Planning wird danach in einer neuen Planning-Sitzung
für dieselbe Planning-Bead wieder in `PLAN_INTERACTIVE` aufgenommen. Ein
technischer Session-Fork ist keine Voraussetzung, und `SESSION_HANDOFF` erzeugt
keine endgültigen `bd`-Vorgänge, Untervorgänge oder Abhängigkeiten.

Nach zwei erfolglosen Runden derselben Beanstandung wird deterministisch
eskaliert. Der Reviewer darf nur Abweichungen vom freigegebenen Plan, von
maßgeblichen Quellen oder von überprüfbaren Vollständigkeitskriterien melden.

### Implementation-Workflow

```text
IMPLEMENT_PREPARE
→ RALPHEX_EXECUTE
→ RALPHEX_REVIEW
→ VERIFY_RESULT
→ FAST_FORWARD_INTEGRATE
→ CLOSE
```

Ausführung und Review sind getrennte Ralphex-Läufe auf demselben isolierten
Arbeitszweig. Dadurch können Implementierer und Reviewer verschiedene
Executor verwenden. Ein KI-Rollenergebnis gilt erst nach erfolgreicher Prüfung
des Executor-Vertrags nach Abschnitt 9.4 als angenommen. Fehler, Zeitlimit,
Rate-Limit ohne erfolgreiche Wiederaufnahme, Review-Sackgasse oder
Integrationskonflikt führen zu `PAUSED`, niemals zu `close`.

## 8. Schreibgrenzen und Git-Sicherheit

### Planung

```text
Produktcode          read-only
Planungsdokumente    read-write gemäß konfigurierter Pfade
bd-Graph             read-write
Laufzustand          nur durch Orchestrator
```

Die kontrollierte Planfortschreibung nutzt dieselben Grenzen, schreibt darin
aber nur `plan.md`.

### Umsetzung

```text
Code, Tests und betroffene Doku   read-write im isolierten Worktree
andere Worktrees                   kein Zugriff
bd-Status und close                nur durch Orchestrator
Push/Deployment                    verboten
```

Die erste Version setzt das durch eine Kombination aus isoliertem Worktree,
technisch getrennten Mounts und einer Diff-Prüfung vor Integration durch. Für
Planning erhält der gestartete Prozess den Produktcode nur read-only, einen
konfigurierten Doku-Bereich sowie den `bd`-Bereich read-write; Laufzustand
bleibt ausschließlich beim Orchestrator. Beispiel: `src/` und `tests/` sind
read-only, `docs/` und `.beads/` read-write. Die Pfad-Konfiguration erzwingt
diese Mount-Grenze, ohne vorwegzunehmen, welche Dokumente der
Planungs-Umsetzer ändern wird. Der Reviewer und das Diff-Gate prüfen
anschließend, dass die Änderungen innerhalb des Doku-Bereichs begründet sind.
Änderungen am `bd`-Bestand erfolgen ausschließlich über die `bd`-CLI;
direkter Dateizugriff auf `.beads/` ist trotz benötigter Schreibberechtigung
nicht Teil des Agentenvertrags. Die Mount-Grenze und das Diff-Gate sind
deterministische Kontrollen; der Reviewer prüft danach KI-basiert die
inhaltliche Begründung. Der ursprüngliche Arbeitsbaum wird niemals automatisch
zurückgesetzt oder überschrieben.

Vor jedem schreibenden Lauf gelten diese Gates:

- Ausgangsbranch und Ausgangscommit sind gespeichert;
- Arbeitsbaum ist sauber oder der Lauf verweigert den Start;
- kein zweiter `ki-dev`-Lauf hält das Repository-Lock;
- die ausgewählte Bead ist offen, unblocked und eindeutig;
- `doctor` hat keine inkompatible Toolversion festgestellt.

Nach Erfolg:

- mindestens ein erwarteter Commit existiert, außer ein dokumentierter
  No-op-Fall wurde reviewed;
- vorgeschriebene Prüfungen sind grün;
- der erlaubte Diff-Umfang ist eingehalten;
- Integration ist Fast-forward;
- erst dann wird der `bd`-Vorgang geschlossen.

## 9. Executor- und Modellzuordnung

### 9.1 Grundsatz

`ki-dev` löst für jede Agentenrolle in `.ki-dev/config.toml` ein konkretes
Modellprofil auf. Ein Profil enthält Executor, Modell und Effort. Diese
Zuordnung ist deterministisch. Agenten dürfen sie nicht verändern.

Leitregel in Ergänzung zu Abschnitt 2:

```text
Prompt:
Denken, Interpretation, Qualitätsurteil und Formulierung

Orchestrator:
Ablauf, aktuelle Bead-ID, Schreibrechte, Zustände, Gates,
Executor- und Modellwahl, Commit-/Integrationsprüfung und close
```

### 9.2 Modellprofile, Rollen und Overrides

Benannte Modellprofile sind bereits konkrete Zuordnungen, keine zusätzliche
Tier-Logik. Rollen verweisen auf ein Profil. Ein optionaler Rollen-Override
und anschließend ein einmaliger Lauf-Override können Werte ersetzen. Danach
muss eine vollständige, verfügbare Kombination aus Executor, Modell und Effort
vorliegen; andernfalls bricht `ki-dev` vor dem Rollenstart mit einem
Konfigurationsfehler ab. Fallbacks, Warnungen oder das Verwerfen eines Teils
der Modellangabe gelten nicht als gültige Auflösung.

```toml
[models.work]
executor = "claude"
model    = "sonnet"
effort   = "high"

[models.control]
executor = "codex"
model    = "sol"
effort   = "high"

[roles]
planner               = "control"
plan_write_controller = "control"
plan_writer           = "work"
session_handoff       = "control"
plan_materializer     = "work"
plan_reviewer         = "control"
implementer           = "work"
impl_reviewer         = "control"

[role_overrides.impl_reviewer]
effort = "xhigh"
```

Der Adapter leitet die versionierte Rollenangabe über Profil und mögliche
Overrides in die jeweilige CLI-Schnittstelle ab. `ki-dev doctor` prüft die
vollständige Abbildbarkeit gegen die gepinnten Executor- und Ralphex-Versionen.

### 9.3 Rollenzuordnung und Invarianten

| Rolle | Phase | Ausführung |
| --- | --- | --- |
| Planer | `PLAN_INTERACTIVE` | `ki-dev`-Agentenadapter |
| Schreibkontroller (`plan_write_controller`) | `PLAN_INTERACTIVE`, kontrollierte Planfortschreibung | `ki-dev`-Agentenadapter |
| Schreibagent (`plan_writer`) | `PLAN_INTERACTIVE`, kontrollierte Planfortschreibung | `ki-dev`-Agentenadapter |
| Übergabe-Agent (`session_handoff`) | `SESSION_HANDOFF` | `ki-dev`-Agentenadapter |
| Planungs-Umsetzer | `MATERIALIZE` | `ki-dev`-Agentenadapter |
| Planungs-Reviewer | `REVIEW` | `ki-dev`-Agentenadapter |
| Implementierer | `RALPHEX_EXECUTE` | Ralphex `--tasks-only` |
| Implementation-Reviewer | `RALPHEX_REVIEW` | Ralphex `--review` |

`ki-dev doctor` und der Orchestrator erzwingen:

- Planungs-Umsetzer und Planungs-Reviewer verwenden verschiedene Executor.
- Implementierer und Implementation-Reviewer verwenden verschiedene Executor.
- Die Pflicht zur Executor-Trennung gilt ausschließlich für diese beiden
  beschlossenen echten Umsetzer-/Reviewer-Paare. Für `plan_write_controller`
  und `plan_writer` (`CONTROLLED_WRITE`) wird in V1 keine Executor-Trennung
  verlangt; verschiedene Modellprofile `control` und `work` allein bedeuten
  nicht automatisch verschiedene Executor.
- Jedes in `[roles]` verwendete Modellprofil existiert.
- Profil und Rollen-Override ergeben eine vollständige und verfügbare
  Zuordnung.
- Lokale Ralphex-Einstellungen dürfen die von `ki-dev` bestimmte Zuordnung
  nicht überschreiben.
- Kein gestarteter Agent erhält Schreibzugriff auf die Executor- oder
  Modellkonfiguration.

Der Implementierungs- und Review-Lauf verwenden denselben isolierten
Arbeitszweig. Der Implementierungslauf erzeugt den Worktree; der Review-Lauf
startet anschließend darin und prüft gegen den gespeicherten `base_commit`.

### 9.4 Lauf-Override und Laufzeitprüfung

Ein Lauf darf eine Rollenangabe ausdrücklich überschreiben, etwa:

```bash
ki-dev run bd-i103 --role-model implementer=codex:sol:high
```

Die Auflösung lautet: Modellprofil → Rollen-Override → Lauf-Override →
Executor, Modell und Effort. Der Lauf-Override verändert `config.toml` nicht
und muss dieselben Verfügbarkeits- und Invariantenprüfungen bestehen. Eine
automatische Modellwahl oder Hochstufung gibt es in V1 nicht.

Jeder Rollenstart erzeugt einen strukturierten Ausführungsnachweis mit
mindestens `role`, `attempt`, `configured_executor`, `configured_model`,
`configured_effort`, `observed_executor`, `observed_model` und
`observed_effort`. Soweit der jeweilige Executor diese Angaben zuverlässig
bereitstellt, vergleicht der Adapter Soll- und Ist-Werte, bevor er das
Rollenergebnis akzeptiert.

Für jede konfigurierte Angabe legt der gepinnte Executor-Vertrag fest, ob sie
zur Laufzeit verlässlich beobachtbar ist. Nur solche Angaben werden zur
Soll-/Ist-Prüfung herangezogen. Ist eine laut Executor-Vertrag erforderliche
Beobachtung nicht verfügbar, wird das Rollenergebnis nicht akzeptiert und der
Lauf geht nach `PAUSED`.

Weichen beobachteter Executor, Modell oder Effort von der aufgelösten
Konfiguration ab, wird das Ergebnis nicht akzeptiert und der Lauf geht nach
`PAUSED`. Welche Angaben je Executor zuverlässig beobachtbar sind, ist Teil des
gepinnten Executor-Vertrags aus Phase 0.

## 10. Umsetzungsphasen für dieses Repository

### Phase 0 – externe Verträge festnageln

- unterstützte Mindestversionen von `bd` und Ralphex festlegen;
- JSON-Schemas und Integrationstests nur für `bd ready`, `show`, `claim`,
  `create`, `dep` und `close` erfassen;
- Ralphex ausschließlich für die V1-Schnittstellen in einem Toy-Repository
  prüfen: Plan-Datei ausführen, Worktree/Branch, Exitstatus und
  Reviewabschluss.
- Verhalten der gepinnten Ralphex-Version für getrennte Ausführungs- und
  Review-Läufe, Modell-/Effort-Angaben, `--wait` und das Format der
  Laufzeitidentität festhalten.

Ergebnis: eine kleine Kompatibilitätsmatrix, die auch `doctor` verwendet.

### Phase 1 – CLI-Scaffold, `init` und `doctor`

- ausführbares `ki-dev`-Binary, Argumentparser und strukturierte Fehler bauen;
- Konfigurationsformat und Projektwurzel-Erkennung implementieren;
- `make build`, `make test` und `make install` bereitstellen;
- idempotentes `init` einschließlich Vorschau vorhandener Dateien bauen;
- `doctor` mit hilfreichen Reparaturbefehlen umsetzen;
- Unit-Tests mit simulierten Toolausgaben ergänzen.
- Konfigurationsschema und `doctor`-Prüfungen der Executor-Invarianten bauen.

Abnahme: Ein frisches Git-Repository wird mit der in Abschnitt 4 gezeigten
Befehlsfolge vollständig eingerichtet oder mit einer eindeutigen
Reparaturanweisung verlassen.

### Phase 2 – `bd`-Adapter und Dispatcher

- alle `bd`-Aufrufe zentral kapseln und JSON strikt auswerten;
- Workflow-Labels und Default auf Implementation implementieren;
- deterministische Auswahl nach Priorität, Erstellungszeit und ID festlegen;
- Race beim Claim erkennen und mit dem nächsten Kandidaten fortfahren;
- Run-Lock, `state.json`, `ready`, `status`, `logs` und `resume` bauen;
- beweisen, dass nach Auswahl keine neue Bead-ID verwendet wird.

Abnahme: Ein Fixture-Graph mit blockierten und ready Vorgängen wird in stabiler
Reihenfolge verarbeitet; Graphänderungen während des Laufs wechseln den
Arbeitsgegenstand nicht.

### Phase 3 – Planning-Workflow

- interaktiven Planer-Adapter mit gespeichertem Gesamtplan-Freigabe-Gate
  (`HUMAN_APPROVAL`) bauen; dieses Gate ist von der `WRITE`-Auslösung der
  kontrollierten Planfortschreibung getrennt;
- Übergabeformat des freigegebenen Gesamtplans zwischen Planer und
  Planungs-Umsetzer definieren;
- `MATERIALIZE` erst nach `HUMAN_APPROVAL` starten: der Planungs-Umsetzer
  überführt den freigegebenen Gesamtplan in die betroffene Projektdokumentation
  und erzeugt die `bd`-Vorgänge, Untervorgänge und Abhängigkeiten;
- neu erzeugte Vorgänge bis zum Abschluss an die Planning-Bead binden;
- Reviewer-Vertrag `PASS | CHANGES | ESCALATE` strikt parsen;
- Korrekturschleife und Sackgassenerkennung implementieren;
- getrennte Dokumentations- und Agentenrichtlinien aus den Rollen-Prompts
  referenzieren und im Review anwenden;
- den `ki-dev`-eigenen Agent-Adapter für den einen interaktiven Planerstart und
  die nicht-interaktiven Planning-Rollenstarts aus Abschnitt 9.3
  (`plan_write_controller`, `plan_writer`, Planungs-Umsetzer, Planungs-Reviewer;
  `session_handoff` gemäß Abschnitt 2) mit Profil-, Override-
  und Mount-Parametern bauen;
- die menschliche `WRITE`-Eingabe im Planer-Adapter als Auslöser der
  kontrollierten Planfortschreibung erkennen und dabei `WRITE` mit neuem
  Planungsinhalt von `WRITE` ohne neuen Planungsinhalt (nur Zustimmung oder
  Freigabe der unmittelbar vorherigen Planerausgabe) unterscheiden; diese
  fachliche Unterscheidung trifft der interaktive Planer, der Orchestrator
  erzwingt nur die daraus folgende Reihenfolge;
- die Freigaberegel vor jeder Snapshot-Erzeugung umsetzen: bei `WRITE` ohne
  neuen Inhalt gilt die unmittelbar vorherige Planerausgabe als bestätigt; bei
  `WRITE` mit neuem Inhalt verlangt der Orchestrator zuerst eine weitere
  sichtbare Planerausgabe, die diesen Inhalt verarbeitet, und danach eine
  ausdrückliche menschliche Bestätigung dieser Ausgabe;
- die Snapshot-Sperre erzwingen: solange neuer Inhalt einer `WRITE`-Eingabe noch
  nicht in einer vom Menschen bestätigten Planerausgabe verarbeitet ist, wird
  weder ein Snapshot erzeugt noch ein `CONTROLLED_WRITE` gestartet;
- aus dem so freigegebenen Planning-Kontext einen für diesen `CONTROLLED_WRITE`
  unveränderlichen Snapshot erzeugen und ihn fest an diesen `CONTROLLED_WRITE`
  binden; als zu prüfendes einfaches V1-Modell kann der Planning-Kontext die
  Folge der Planerausgaben der bewusst kleinen Planning-Sitzung bis zur
  bestätigten Ausgabe sein (Abschnitt 2); dieses Modell wird in Phase 3 geprüft,
  aber nicht als einziges Snapshot-Modell für V1 festgelegt; eine konkrete
  technische Snapshot-Darstellung oder Datei-/JSON-Struktur legt Phase 3 nicht
  fest;
- den erzeugten Snapshot als reinen Schreibeingang an den `plan_write_controller`
  übergeben; die Planning-Sitzung darf danach weiterlaufen, ohne den an seinen
  eingefrorenen Eingang gebundenen `CONTROLLED_WRITE` zu verändern;
- die `WRITE`-Freigaberegel strikt von `HUMAN_APPROVAL` und `MATERIALIZE`
  getrennt halten: die Bestätigung einer Planerausgabe für einen Snapshot ist
  keine Gesamtplan-Freigabe; der Snapshot ist reiner Schreibeingang, der
  `CONTROLLED_WRITE` schreibt nur `plan.md`, und dabei entstehen keine
  endgültigen `bd`-Vorgänge, Untervorgänge oder Abhängigkeiten;
- den `CONTROLLED_WRITE`-Lebenszyklus umsetzen: der `plan_write_controller`
  (Profil `control`, nicht-interaktiv) bestimmt je Schreibschnitt einen
  begrenzten `TASK` aus Snapshot und aktuellem geprüften `plan.md`, bei weiteren
  Schreibschnitten zusätzlich aus den bisherigen `CONTROLLED_WRITE`-Ergebnissen;
  pro Schreibschnitt startet ein frischer `plan_writer`
  (Profil `work`); innerhalb eines Schreibschnitts übernimmt bei `CHANGES`
  derselbe `plan_writer`; erst nach `PASS_STEP` folgt der nächste `TASK` oder
  der Abschluss des `CONTROLLED_WRITE`;
- den über alle Schreibschnitte und Korrekturschleifen zusammenhängenden
  Kontroller-Zustand allein aus freigegebenem Planning-Snapshot, aktuellem
  geprüften `plan.md` und den bisherigen Ergebnissen des laufenden
  `CONTROLLED_WRITE` rekonstruierbar halten, ohne executor-spezifische
  Sitzungsfortsetzung;
- die Rückeskalation des `plan_write_controller` zu Planning bei fehlender
  fachlicher oder architektonischer Entscheidung umsetzen;
- den `SESSION_HANDOFF` als persistierte Orchestrator-Phase desselben
  Planning-Workflows und derselben Planning-Bead umsetzen (Vertrag siehe
  Abschnitt 2), nicht als neue Planning-Bead und nicht als neuen fachlichen
  Planning-Vorgang: ausgelöst durch den Menschen oder durch das Signal einer
  unterstützenden Größenbegrenzung; `ki-dev` legt dafür keine konkrete feste
  Größen-, Token- oder Turn-Schwelle fest, ein unterstützendes
  Größenbegrenzungssignal bleibt zulässig;
- während dieser Phase `state.json.phase = SESSION_HANDOFF` desselben Laufs
  persistieren, sodass ein Abbruch bzw. `ki-dev resume` eindeutig bei
  `SESSION_HANDOFF` wiederaufnimmt; dafür keine neue Zustandsdatei und kein
  neues Schema einführen, sondern das bestehende Feld `phase` verwenden;
- dabei die eigene nicht-interaktive Rolle `session_handoff` (Profil `control`)
  über den `ki-dev`-eigenen Agent-Adapter starten und die nötige Profil-/
  Override-Auflösung gemäß dem allgemeinen Rollenvertrag durchführen;
- der Übergabe-Agent wertet den bisherigen Planning-Kontext der zu groß
  gewordenen Sitzung chronologisch aus und erzeugt daraus eine flache
  Fortsetzungsübergabe für eine neue Planning-Sitzung; ein Rohtranskript kann als
  Rückfallquelle erhalten bleiben, ohne dass der Kernvertrag seine Aufbewahrung
  verlangt;
- `ki-dev` führt die zu groß gewordene Sitzung nicht weiter als regulären
  Planning-Kontext fort und setzt das Planning über `SESSION_HANDOFF` in einer
  neuen Planning-Sitzung für dieselbe Planning-Bead fort; die
  Fortsetzungsübergabe ist die reguläre Grundlage dieser neuen Sitzung, ein
  etwaig erhaltenes Rohtranskript dient höchstens als Rückfallquelle;
- die Korrektheit dieses Übergangs nicht von einem technischen Session-Fork,
  einem Klon oder einer executor-spezifischen Sitzungsfortsetzung abhängig
  machen;
- sicherstellen, dass `SESSION_HANDOFF` keine Projektdokumentation und keine
  endgültigen `bd`-Vorgänge, Untervorgänge oder Abhängigkeiten erzeugt; spätere
  kontrollierte Planfortschreibungen und die spätere `MATERIALIZE` bleiben davon
  unabhängige Vorgänge;
- die technische Mount-Grenze für Planung erzwingen: Produktcode read-only,
  konfigurierter Doku-Bereich und `bd` read-write; Diff-Prüfung und
  Reviewer-Gate als zweite Sicherung ergänzen.

Abnahme: Im VPS-Beispiel schreibt mindestens eine kontrollierte
Planfortschreibung während der laufenden Planning-Sitzung einen Zwischenstand
nach `plan.md`, ohne `bd`-Vorgänge, Untervorgänge oder Abhängigkeiten zu
erzeugen. Erst nach der menschlichen Freigabe des Gesamtplans erzeugt
`MATERIALIZE` aus dem Planning-Vorgang eine geprüfte Architekturdoku und drei
korrekt abhängige Implementation-Vorgänge, ohne Produktcode zu verändern.

Abnahme (WRITE-/Snapshot-Vertrag): Im VPS-Beispiel werden beide `WRITE`-Fälle
geprüft. Fall 1: Eine `WRITE`-Eingabe ohne neuen Inhalt löst die kontrollierte
Planfortschreibung aus und bestätigt die unmittelbar vorherige Planerausgabe;
daraufhin entsteht gemäß Freigaberegel genau ein unveränderlicher Snapshot, der
dem `plan_write_controller` als eingefrorener Schreibeingang des
`CONTROLLED_WRITE` übergeben wird. Fall 2: Eine `WRITE`-Eingabe mit neuem Inhalt
erzeugt zunächst keinen Snapshot; erst nach einer weiteren sichtbaren
Planerausgabe, die den Inhalt verarbeitet, und deren ausdrücklicher menschlicher
Bestätigung entstehen Snapshot und anschließend `CONTROLLED_WRITE`. In beiden
Fällen läuft die Planning-Sitzung danach weiter, der Snapshot bleibt unverändert
an seinen `CONTROLLED_WRITE` gebunden, und es entstehen keine `bd`-Vorgänge,
Untervorgänge oder Abhängigkeiten; die `WRITE`-Bestätigung wird nicht als
`HUMAN_APPROVAL` gewertet.

Abnahme (Session-Handoff): Im selben VPS-Beispiel wird eine absichtlich zu groß
gewordene Planning-Sitzung über einen `SESSION_HANDOFF` fortgesetzt. Die Rolle
`session_handoff` erzeugt aus dem bisherigen Planning-Kontext eine
Fortsetzungsübergabe; eine neue Planning-Sitzung für dieselbe Planning-Bead
nimmt das Sachthema regulär auf deren Grundlage wieder auf. Ein Rohtranskript
muss dafür nicht aufbewahrt werden. Danach ist zum selben Sachthema mindestens
eine weitere kontrollierte Planfortschreibung nach `plan.md` möglich – ohne
technischen Session-Fork und ohne dass `SESSION_HANDOFF` `bd`-Vorgänge,
Untervorgänge oder Abhängigkeiten erzeugt.

### Phase 4 – Ralphex-Implementation-Adapter

- `bd`-Task-Schema validieren und in einen Ein-Vorgang-Ralphex-Plan rendern;
- Ralphex mit projektspezifischen Prompts, Branch und Worktree starten;
- Ausgabe, Exitcode, Fortschritt, Commits und Reviewabschluss erfassen;
- erfolgreichen Branch ausschließlich per Fast-forward integrieren;
- erst nach Integration `bd close` ausführen;
- `Ctrl-C`, Toolfehler und erneuten Start korrekt behandeln.
- Ausführung und Review als getrennte Ralphex-Läufe auf demselben Arbeitszweig
  starten, Modellangaben übergeben und Laufzeitidentitäten auswerten;
- die Profile und Overrides in Modellparameter, Ausführungsnachweis und
  Laufzeitprüfung auflösen.

Abnahme: Ein kleiner echter Codevorgang wird implementiert, getestet, reviewed,
committet, integriert und genau einmal geschlossen.

### Phase 5 – Härtung der Orchestrierung

- Schreibgrenzen und verbotene Pfade mit Negativtests absichern;
- Timeouts, Rate-Limits und wiederholte identische Reviews behandeln;
- atomare Zustandsübergänge und Crash-Recovery testen;
- `run --loop` bis `NO_READY`, `PAUSED` oder `ESCALATE` umsetzen;
- keine automatischen Push-, Merge-Conflict- oder Reset-Aktionen zulassen.
- Negativtests für ungültige Profilauflösungen, nicht beobachtbare
  `control`-Identitäten und widersprüchliche lokale Ralphex-Einstellungen
  ergänzen.

Abnahme: Prozessabbruch in jeder Phase lässt einen verständlichen,
wiederaufnehmbaren Zustand zurück und schließt keinen unvollständigen Vorgang.

### Phase 6 – echte Ende-zu-Ende-Nutzung

- ein Fixture-Projekt automatisch initialisieren;
- darin einen Planning-Workflow mit Benutzerfreigabe simulieren;
- erzeugte Implementation-Vorgänge der Reihe nach durch Ralphex ausführen;
- Abhängigkeiten, Commits, Doku, Tests, Resume und Abschlusszustände prüfen;
- anschließend dieses Repository selbst mit `ki-dev` weiterentwickeln;
- Installations-, Betriebs- und Fehlerdokumentation aus der tatsächlichen
  Nutzung korrigieren.

Abnahme: Die vollständige Befehlsfolge aus Abschnitt 11 funktioniert ohne
manuelle `bd`- oder Ralphex-Zustandsreparatur.

## 11. Vollständige Abnahmestrecke

```bash
# einmalig auf dem Rechner
brew install beads
mkdir -p ~/.local/bin
curl -fsSL \
  https://raw.githubusercontent.com/umputun/ralphex/master/scripts/ralphex-dk.sh \
  -o ~/.local/bin/ralphex
chmod +x ~/.local/bin/ralphex

# einmalig im Zielprojekt
cd /pfad/zum/projekt
ki-dev init
ki-dev doctor

# neue Arbeit
ki-dev plan "VPS-Service mit reproduzierbarem Deployment"

# Ergebnis ansehen
ki-dev ready
ki-dev status

# einen Vorgang kontrolliert ausführen
ki-dev run bd-b200

# verbleibende ausführbare Arbeit autonom fortsetzen
ki-dev run --loop

# bei Unterbrechung oder Entscheidungsbedarf
ki-dev status
ki-dev logs bd-b200
ki-dev resume bd-b200
```

Erwartetes Endergebnis:

```text
Planning-Bead:             closed
Implementation-Beads:     closed oder fachlich blockiert
Abhängigkeiten:            eingehalten
Planungsdokumentation:     integriert
Code und Tests:            integriert und grün
Reviews:                   bestanden
Commits:                   vorhanden und den Beads zuordenbar
Push/Deployment:           nicht automatisch ausgeführt
Aktiver ki-dev-Lauf:       keiner
```

## 12. Bewusste Nicht-Ziele

In der ersten Version werden nicht gebaut:

- eine Pages-PM-artige Prüfschicht;
- eine zweite Aufgaben- oder Spezifikationsdatenbank;
- ein `implements`-Metamodell;
- allgemeine Spec-/Graph-Validierung über die für den Ablauf nötigen
  Konsistenzprüfungen hinaus;
- beliebige Dokumenttypen, ADR-/KEP-Generatoren oder weitere Workflow-Typen;
- parallele Multi-Agent-Integration;
- automatischer Push, Pull Request, Release oder Deployment;
- Übernahme beliebiger alter oder externer Chat-Sitzungen; der
  `SESSION_HANDOFF` nach Abschnitt 2 setzt nur die eigene, zu groß gewordene
  Planning-Sitzung fort und schließt das Sachthema nicht ab.
- adaptive Modellwahl anhand von Aufgabeninhalt, Diff-Größe oder
  Agentenurteil;
- automatische Kostenoptimierung oder Modellwahl über die statische Profil-
  und Rollenkonfiguration sowie explizite Lauf-Overrides hinaus;
- Unterstützung für mehr als zwei Executor-Arten in der ersten Version.

Nicht zum erforderlichen V1-Kernentwurf gehören dagegen:

- eine allgemeine Nachrichtenserialisierung der Planning-Kommunikation;
- eine allgemeine Architektur zur Trennung oder Behandlung zusätzlicher
  Ausgabearten neben den eigentlichen Planerausgaben, etwa grammatischer
  Rückmeldungen.

V1 muss diese beiden Punkte weder spezifizieren noch allgemein lösen. Das
verbietet nicht, dass eine konkrete Umsetzung technisch bereits etwas
Entsprechendes nutzt. Sie ändern nichts an den bereits beschlossenen konkreten
Verträgen für Planning-Snapshot, `CONTROLLED_WRITE`, `SESSION_HANDOFF` und
`MATERIALIZE`. Solche allgemeinen Erweiterungen können nach Go-live behandelt
werden.

Nach realer Nutzung kann als erstes optionales Feature folgen:

```bash
ki-dev session <session-id>
```

Es übernimmt einen bereits freigegebenen Plan und startet direkt mit
Planungs-Umsetzer und Planungs-Reviewer. Diese Erweiterung darf den Kernvertrag
„eine Bead-ID pro Lauf“ nicht ändern.

## 13. Referenzierte externe Schnittstellen

- Beads-Dokumentation: <https://github.com/gastownhall/beads>
- Ralphex-Dokumentation: <https://github.com/umputun/ralphex>

Beide Werkzeuge entwickeln sich weiter. Deshalb sind konkrete Fremdflags in
diesem Plan Zielannahmen, die Phase 0 mit gepinnten Versionen bestätigt. Die
öffentliche `ki-dev`-Befehlsoberfläche soll davon stabil bleiben.
