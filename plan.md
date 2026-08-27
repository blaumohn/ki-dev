# Umsetzungsplan: KI-Dev-Arbeitsweise

## 1. Ergebnis

Es entsteht ein lokales Kommandozeilenwerkzeug namens `ki-dev`. Ein Entwickler
startet es im Wurzelverzeichnis eines Git-Repositories. Es verbindet drei
Bausteine:

1. `bd` speichert Vorgänge, Abhängigkeiten, Prioritäten und Zustände dauerhaft.
2. Ralphex führt freigegebene Implementierungspläne aus, testet, reviewed und
   committet sie.
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
Planer ↔ Benutzer        Ralphex-Umsetzung
Planungs-Umsetzer        Tests
Planungs-Reviewer        Reviews und Korrekturen
Doku + bd-Graph          Commit
   ↓                         ↓
Vorgang schließen        Vorgang schließen
   ↓
erst jetzt wieder bd ready
```

## 2. Rollen und Arbeitsarten

Es gibt zwei Arbeitsarten, aber mehrere Rollen.

### Planung

```text
Planer ↔ Benutzer
→ freigegebener Plan
→ Planungs-Umsetzer
→ Planungsdokumentation und bd-Graph
→ Planungs-Reviewer
→ bei Mängeln zurück zum Planungs-Umsetzer
→ Planning-Vorgang schließen
```

- Der Planer versteht Problem, Quellen und Optionen und führt den Dialog mit
  dem Benutzer.
- Der Planungs-Umsetzer materialisiert nur die freigegebenen Entscheidungen.
- Der Planungs-Reviewer vergleicht freigegebenen Plan, tatsächliche Doku und
  tatsächlichen `bd`-Graphen.
- Der Benutzer entscheidet fachliche oder architektonische Fragen und gibt den
  Plan frei.

### Umsetzung

```text
Umsetzer
→ Tests
→ Reviewer
→ Korrekturen
→ abschließende Prüfung
→ Commit
```

Ralphex stellt diesen Zyklus bereits bereit. `ki-dev` erzeugt dafür aus genau
einem `bd`-Vorgang einen ausführbaren Ralphex-Plan und übernimmt anschließend
Integration und Zustandswechsel.

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
| `ki-dev plan "<Ziel>"` | Planning-Vorgang erstellen und interaktiv vollständig ausführen |
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
Docker-Installation. Zusätzlich muss mindestens ein von Ralphex unterstützter
Coding-Agent angemeldet sein, zuerst Codex oder Claude Code; dessen lokale
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
ki-dev init --executor=codex
ki-dev doctor
```

`ki-dev init` ist idempotent und führt nachvollziehbar aus:

1. Git-Repository und Wurzelverzeichnis erkennen.
2. Vorhandene Konfiguration feststellen und geplante Änderungen anzeigen.
3. Falls nötig `bd init --quiet` ausführen.
4. Die passende Agentenintegration von `bd` einrichten.
5. Falls nötig `ralphex --init` ausführen.
6. `.ki-dev/config.toml`, lokale Prompts und Laufverzeichnisse anlegen.
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

- unterstützte Versionen von `bd`, Ralphex, Git und gewähltem Agenten;
- erfolgreiche Agentenanmeldung, soweit die jeweilige CLI dies lokal prüfen
  kann;
- vorhandenes `bd`-Repository und lesbares JSON von `bd ready --json`;
- gültige Ralphex-Konfiguration und erreichbaren Executor;
- eindeutige Projektwurzel und beschreibbare Laufverzeichnisse;
- keinen widersprüchlichen aktiven `ki-dev`-Lauf;
- konfigurierte Schreibgrenzen und vorhandene Promptdateien.

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

Danach beginnt im selben Terminal die starke interaktive Planung:

```text
ki-dev: Planning bd-a1b2
Planer: Welche Betriebsumgebung und welche Ausfallgrenze gelten?
Benutzer: ...
Planer: Ich sehe zwei tragfähige Varianten ...
...
Planer: Zusammenfassung der getroffenen Entscheidungen ...
Plan freigeben? [y/N]
```

Vor `y` wird nichts materialisiert. Nach der Freigabe:

1. speichert `ki-dev` den freigegebenen Plan als Übergabeartefakt des Laufs;
2. startet es den Planungs-Umsetzer;
3. dieser ändert die vereinbarte Planungsdokumentation und erzeugt die
   Implementation-Vorgänge samt Abhängigkeiten;
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

Die interne Reihenfolge für jeden Vorgang ist fest:

```text
bd ready --json
→ Kandidat deterministisch auswählen
→ Bereitschaft erneut prüfen und atomar claimen
→ ID in .ki-dev/runs festschreiben
→ bd show <id> --json
→ Workflow-Label lesen
→ Ein-Vorgang-Ralphex-Plan erzeugen
→ Ralphex in isoliertem Worktree/Branch starten
→ Tests und Reviews durch Ralphex
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

Der geplante Adapteraufruf ist sinngemäß:

```bash
ralphex \
  --codex \
  --worktree \
  --branch=ki-dev/bd-b200 \
  .ki-dev/ralphex/plans/bd-b200.md
```

Die genaue Flag-Kompatibilität wird gegen die im Projekt unterstützte
Ralphex-Version getestet und in `ki-dev doctor` abgesichert. `ki-dev` pusht
nichts. Nach erfolgreichem Ralphex-Lauf wird nur per Fast-forward integriert.
Ist das nicht möglich, bleibt der Vorgang offen und der Benutzer erhält eine
konkrete Integrations-Eskalation.

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
attempt
base_branch und base_commit
work_branch
ralphex_plan und progress_log
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
→ HUMAN_APPROVAL
→ MATERIALIZE
→ REVIEW
   ├─ PASS     → INTEGRATE → CLOSE
   ├─ CHANGES  → MATERIALIZE
   └─ ESCALATE → PAUSED
```

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

Fehler, Zeitlimit, Rate-Limit ohne erfolgreiche Wiederaufnahme, Review-Sackgasse
oder Integrationskonflikt führen zu `PAUSED`, niemals zu `close`.

## 8. Schreibgrenzen und Git-Sicherheit

### Planung

```text
Produktcode          read-only
Planungsdokumente    read-write gemäß konfigurierter Pfade
bd-Graph             read-write
Laufzustand          nur durch Orchestrator
```

### Umsetzung

```text
Code, Tests und betroffene Doku   read-write im isolierten Worktree
andere Worktrees                   kein Zugriff
bd-Status und close                nur durch Orchestrator
Push/Deployment                    verboten
```

Die erste Version setzt das durch eine Kombination aus isoliertem Worktree,
phasenbezogener Pfad-Allowlist und einer Diff-Prüfung vor Integration durch.
Eine unerlaubte Dateiänderung wird nicht integriert. Der ursprüngliche
Arbeitsbaum wird niemals automatisch zurückgesetzt oder überschrieben.

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

## 9. Umsetzungsphasen für dieses Repository

### Phase 0 – externe Verträge festnageln

- unterstützte Mindestversionen von `bd` und Ralphex festlegen;
- JSON-Schemas der benötigten `bd`-Ausgaben mit Fixtures erfassen;
- `create`, Label, Abhängigkeit, `ready`, `claim`, `show` und `close` gegen die
  unterstützte `bd`-Version als Integrationstest ausführen;
- Ralphex-Verhalten für `--worktree`, `--branch`, Planpfad, Exitcodes,
  Planverschiebung und Wiederaufnahme in einem Toy-Repository prüfen;
- entscheiden und testen, wie mehrere Ein-Vorgang-Läufe sicher auf demselben
  Ausgangsbranch aufbauen.

Ergebnis: eine kleine Kompatibilitätsmatrix, die auch `doctor` verwendet.

### Phase 1 – CLI-Scaffold, `init` und `doctor`

- ausführbares `ki-dev`-Binary, Argumentparser und strukturierte Fehler bauen;
- Konfigurationsformat und Projektwurzel-Erkennung implementieren;
- `make build`, `make test` und `make install` bereitstellen;
- idempotentes `init` einschließlich Vorschau vorhandener Dateien bauen;
- `doctor` mit hilfreichen Reparaturbefehlen umsetzen;
- Unit-Tests mit simulierten Toolausgaben ergänzen.

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
- Pfad-Allowlist und Integrationsprüfung für Planungsdoku erzwingen.

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

Abnahme: Ein kleiner echter Codevorgang wird implementiert, getestet, reviewed,
committet, integriert und genau einmal geschlossen.

### Phase 5 – Härtung der Orchestrierung

- Schreibgrenzen und verbotene Pfade mit Negativtests absichern;
- Timeouts, Rate-Limits und wiederholte identische Reviews behandeln;
- atomare Zustandsübergänge und Crash-Recovery testen;
- `run --loop` bis `NO_READY`, `PAUSED` oder `ESCALATE` umsetzen;
- keine automatischen Push-, Merge-Conflict- oder Reset-Aktionen zulassen.

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

Abnahme: Die vollständige Befehlsfolge aus Abschnitt 10 funktioniert ohne
manuelle `bd`- oder Ralphex-Zustandsreparatur.

## 10. Vollständige Abnahmestrecke

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
ki-dev init --executor=codex
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

## 11. Bewusste Nicht-Ziele

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

Nach realer Nutzung kann als erstes optionales Feature folgen:

```bash
ki-dev session <session-id>
```

Es übernimmt einen bereits freigegebenen Plan und startet direkt mit
Planungs-Umsetzer und Planungs-Reviewer. Diese Erweiterung darf den Kernvertrag
„eine Bead-ID pro Lauf“ nicht ändern.

## 12. Referenzierte externe Schnittstellen

- Beads-Dokumentation: <https://github.com/gastownhall/beads>
- Ralphex-Dokumentation: <https://github.com/umputun/ralphex>

Beide Werkzeuge entwickeln sich weiter. Deshalb sind konkrete Fremdflags in
diesem Plan Zielannahmen, die Phase 0 mit gepinnten Versionen bestätigt. Die
öffentliche `ki-dev`-Befehlsoberfläche soll davon stabil bleiben.
