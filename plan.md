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
Ein ausreichend geklärter Zwischenstand kann bereits während derselben
Planning-Sitzung kontrolliert nach `plan.md` fortgeschrieben werden, ohne dass
die Sitzung oder das betreffende Sachthema damit abgeschlossen wäre.

```text
Planer ↔ Benutzer
→ ausreichend geklärter Zwischenstand
→ kontrollierte Planfortschreibung in plan.md
→ zurück in denselben Mensch-Planer-Dialog
...
→ freigegebener Plan
→ Planungs-Umsetzer
→ Planungsdokumentation und bd-Graph
→ Planungs-Reviewer
→ bei Mängeln zurück zum Planungs-Umsetzer
→ Planning-Vorgang schließen
```

- Der Planer versteht Problem, Quellen und Optionen und führt den Dialog mit
  dem Benutzer. Seine Ausgaben bleiben klein genug, dass der Benutzer sie
  vollständig prüfen kann.
- Die kontrollierte Planfortschreibung hält einen geklärten Zwischenstand in
  `plan.md` fest. Sie erzeugt noch keine endgültigen `bd`-Vorgänge,
  Untervorgänge oder Abhängigkeiten. Eine spätere Erkenntnis darf denselben
  Sachbereich durch eine weitere kontrollierte Fortschreibung ergänzen oder
  korrigieren. Sie ist deshalb von der späteren vollständigen
  Planning-Materialisierung zu unterscheiden.
- Der Planungs-Umsetzer materialisiert nur die freigegebenen Entscheidungen.
  Der freigegebene Plan ist zunächst ein Laufartefakt, keine Vorgabe für ein
  neues Dokument: Er entscheidet anhand des Plans und der vorhandenen
  Repository-Struktur, welche bestehende Planungs- oder Architekturdokumentation
  tatsächlich geändert werden muss.
- Der Planungs-Reviewer vergleicht freigegebenen Plan, tatsächliche Doku und
  tatsächlichen `bd`-Graphen.
- Der Benutzer entscheidet fachliche oder architektonische Fragen und gibt den
  Plan frei.

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
- Umsetzer und jeweilige Kontrollrolle verwenden verschiedene Executor.

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
Planer: Ich sehe zwei tragfähige Varianten ...
ki-dev: Zwischenstand kontrolliert nach plan.md fortgeschrieben
        Planning-Sitzung läuft weiter
Planer: Offen ist noch das Secrets-Handling ...
...
Planer: Zusammenfassung der getroffenen Entscheidungen ...
Plan freigeben? [y/N]
```

Ein ausreichend geklärter Zwischenstand darf während derselben
Planning-Sitzung kontrolliert nach `plan.md` fortgeschrieben werden. Das
schließt weder die Planning-Sitzung noch das betreffende Sachthema ab und
erzeugt noch keine endgültigen `bd`-Vorgänge, Untervorgänge oder
Abhängigkeiten. Eine spätere Erkenntnis darf denselben Sachbereich durch eine
weitere kontrollierte Fortschreibung ergänzen oder korrigieren.

Die vollständige Planning-Materialisierung ist davon zu unterscheiden. Sie
erzeugt aus dem freigegebenen Plan die Planungsdokumentation und die konkreten
`bd`-Vorgänge. Vor `y` wird nichts materialisiert. Nach der Freigabe:

1. speichert `ki-dev` den freigegebenen Plan als Übergabeartefakt des Laufs;
2. startet es den Planungs-Umsetzer;
3. dieser bestimmt aus Plan und vorhandener Repository-Struktur, ob und welche
   bestehende Planungs- oder Architekturdokumentation geändert werden muss,
   und erzeugt die Implementation-Vorgänge samt Abhängigkeiten;
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

Taskbeschreibung und Status werden nicht dupliziert; sie werden aus `bd`
gelesen. Fachentscheidungen werden nicht nur im Laufzustand aufbewahrt, sondern
vom Planungs-Umsetzer in die vorgesehene Projektdokumentation übertragen.

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
   ├─ kontrollierte Planfortschreibung → PLAN_INTERACTIVE
   └─ Plan ausreichend fertig          → HUMAN_APPROVAL
HUMAN_APPROVAL
→ MATERIALIZE
→ REVIEW
   ├─ PASS     → INTEGRATE → CLOSE
   ├─ CHANGES  → MATERIALIZE
   └─ ESCALATE → PAUSED
```

Die kontrollierte Planfortschreibung bleibt innerhalb von `PLAN_INTERACTIVE`.
Sie schreibt nur `plan.md`, beendet die Planning-Sitzung nicht und erzeugt
keine endgültigen `bd`-Vorgänge, Untervorgänge oder Abhängigkeiten; diese
entstehen erst in `MATERIALIZE`. Derselbe Sachbereich darf im weiteren Verlauf
der Sitzung erneut fortgeschrieben werden.

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

Die kontrollierte Planfortschreibung während der Planning-Sitzung nutzt
dieselben Grenzen, schreibt darin aber nur `plan.md`. Der `bd`-Graph wird erst
in `MATERIALIZE` geschrieben.

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
planner           = "control"
plan_materializer = "work"
plan_reviewer     = "control"
implementer       = "work"
impl_reviewer     = "control"

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
| Planungs-Umsetzer | `MATERIALIZE` | `ki-dev`-Agentenadapter |
| Planungs-Reviewer | `REVIEW` | `ki-dev`-Agentenadapter |
| Implementierer | `RALPHEX_EXECUTE` | Ralphex `--tasks-only` |
| Implementation-Reviewer | `RALPHEX_REVIEW` | Ralphex `--review` |

`ki-dev doctor` und der Orchestrator erzwingen:

- Planungs-Umsetzer und Planungs-Reviewer verwenden verschiedene Executor.
- Implementierer und Implementation-Reviewer verwenden verschiedene Executor.
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

- interaktiven Planer-Adapter mit gespeichertem Freigabe-Gate bauen;
- Übergabeformat zwischen Planer und Planungs-Umsetzer definieren;
- Planungs-Umsetzer für Doku und `bd`-Graph starten;
- neu erzeugte Vorgänge bis zum Abschluss an die Planning-Bead binden;
- Reviewer-Vertrag `PASS | CHANGES | ESCALATE` strikt parsen;
- Korrekturschleife und Sackgassenerkennung implementieren;
- getrennte Dokumentations- und Agentenrichtlinien aus den Rollen-Prompts
  referenzieren und im Review anwenden;
- den `ki-dev`-eigenen Agent-Adapter für einen interaktiven und drei
  nicht-interaktive Rollenstarts mit Profil-, Override- und Mount-Parametern
  bauen;
- die technische Mount-Grenze für Planung erzwingen: Produktcode read-only,
  konfigurierter Doku-Bereich und `bd` read-write; Diff-Prüfung und
  Reviewer-Gate als zweite Sicherung ergänzen.

Abnahme: Das VPS-Beispiel erzeugt aus einem Planning-Vorgang eine geprüfte
Architekturdoku und drei korrekt abhängige Implementation-Vorgänge, ohne
Produktcode zu verändern.

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
- Übernahme beliebiger alter Chat-Sitzungen.
- adaptive Modellwahl anhand von Aufgabeninhalt, Diff-Größe oder
  Agentenurteil;
- automatische Kostenoptimierung oder Modellwahl über die statische Profil-
  und Rollenkonfiguration sowie explizite Lauf-Overrides hinaus;
- Unterstützung für mehr als zwei Executor-Arten in der ersten Version.

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
