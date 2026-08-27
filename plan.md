Ja. Ich würde den Arbeitsablauf jetzt so umbauen, dass **du nicht mehr der laufende Reviewer jedes Diffs bist**, sondern nur noch an wenigen Stellen Entscheidungen triffst. Der Planer und ein eigener Reviewer-Agent übernehmen genau die Rolle, die du bisher interaktiv ausgeübt hast.

Der wichtigste Punkt vor allem anderen: Der derzeitige `zustand.md`-Plan ist für das neue Ziel tatsächlich zu breit. Er verlangt vor Schritt 5 noch einen vollständigen normativen Testabgleich und führt später eine vollständige Dokumentationskohärenzprüfung vor Go-live auf.   Gleichzeitig ist der eigentliche fachliche Go-live-Maßstab schon viel enger angelegt: vollständiger Vorgangsweg, Audit, Beziehungen, gemeinsame Lesesicht, dünner Schreibweg und echter End-to-End-Fall; Renderer und weitere Facharten sind ausdrücklich nicht erforderlich.  Auch die Produktspezifikation nennt als nächsten sachlichen Meilenstein einen vollständigen echten Vorgangslebenslauf. 

# Zielbild des neuen Arbeitsablaufs

```text
EINMALIG
Arbeitsumgebung + Agentenregeln einrichten
        ↓
neuen Go-live-Schnitt in zustand.md festhalten
        ↓
Planer erzeugt bd-Graph
        ↓
DU prüfst nur den Graphen                    ← Tor 1
        ↓

FÜR DIE UMSETZUNG
Orchestrator
    ↓
Umsetzer
    ↓
Tests
    ↓
Reviewer-Agent
    ├─ PASS       → Task abschließen
    ├─ CHANGES    → zurück zum Umsetzer
    └─ ESCALATE   → nur dann zu dir
        ↓
nächster bd-ready-Task

        ↓
kritischer Gesamtlauf + echter E2E
        ↓
DU prüfst Go-live-Freigabe                   ← Tor 2
        ↓
GO-LIVE

DANACH
konkrete aufgeschobene Tests/Doku
+ tatsächlicher Nutzungsbedarf
→ neuer Planungsdurchlauf
```

**Deine normale Arbeit verschiebt sich damit von „Diff für Diff korrigieren“ zu „Graph einmal richtig schneiden“.** Ein Satz wie „das ist nicht ganz richtig“ sollte im normalen Ablauf vom Reviewer-Agenten kommen, nicht mehr von dir.

---

# Phase 0 – neue Arbeitsumgebung einmalig einrichten

Das würde ich **vor der nächsten Pages-PM-Planungssitzung** erledigen.

## 0.1 Vier Rollen fest definieren

| Rolle            | Aufgabe                                                           | Darf entscheiden?                                 |
| ---------------- | ----------------------------------------------------------------- | ------------------------------------------------- |
| **Planer**       | Quellen lesen, Arbeit zerlegen, Abhängigkeiten bauen              | nein, nur aus bestehenden Entscheidungen ableiten |
| **Umsetzer**     | genau einen freigegebenen Task umsetzen                           | nein                                              |
| **Reviewer**     | Diff gegen Task + maßgebliche Quellen prüfen                      | nein                                              |
| **Orchestrator** | Tasks auswählen, Schleife steuern, Prüfungen ausführen, schließen | nein                                              |

Du bist außerhalb dieser Schleife die **Entscheidungsinstanz für echte offene Fragen**.

Das ist wichtig: Der Reviewer soll nicht einfach ein zweiter Entwickler sein. Er soll gezielt nach dem Problem suchen, das dich bisher zum Eingreifen zwang:

```text
Ist zwar technisch plausibel,
aber nicht genau das beschlossene Modell.

Ist funktional richtig,
dupliziert aber eine bestehende Regel.

Test ist grün,
weist aber nicht die normative Aussage nach.

Kommentar ist wahr,
macht die Migration aber wieder zur zweiten Spezifikation.

Diff löst den Task,
ändert nebenbei aber ein anderes Modellstück.
```

Gerade dein Beispiel mit der Migrationsprosa gehört in diesen Prüfvertrag.

## 0.2 Einen einzigen Agentenvertrag im Repository

Nicht dieselben Regeln in fünf Agentenaufforderungen kopieren.

Der automatisch gelesene Agentenvertrag sollte sehr kurz enthalten:

```text
Quellenrang:
product_spec.de.md
system_design.de.md
development_guidelines.de.md
zustand.md
bd-Task

Nicht erneut aufrollen:
→ zustand.md §7

Bei Konflikt:
→ nicht selbst entscheiden
→ ESCALATE

Taskgrenze:
→ keine angrenzende Verbesserung ohne Taskgrund

Kommentare:
→ development_guidelines.de.md §1.5

Eine Regel, eine Implementierung:
→ development_guidelines.de.md §§2–3

Tests:
→ beweisen Akzeptanzkriterium, nicht bloß grünen Lauf erzeugen

Dokumentation:
→ keine unabhängige zweite Festlegung
```

`zustand.md` enthält die bestehenden Nicht-wieder-aufrollen-Regeln bereits ausdrücklich.  Der Agentenvertrag sollte sie daher **nicht neu fachlich formulieren**, sondern auf diese maßgebliche Stelle verweisen.

## 0.3 Ein festes Task-Schema

Jeder umsetzbare `bd`-Task sollte dieselbe Form haben:

```text
Ziel
Go-live-Klasse: PRE | POST

Maßgebliche Quellen
- genaue Abschnitte / Regelkennungen

Warum vor Go-live?
- Schaden beim Aufschieben

Umfang
- was dieser Diff tun soll

Nicht Teil dieses Tasks
- explizite Grenzen

Akzeptanzkriterien
- beobachtbar / testbar

Prüfbefehle
- gezielte Tests
- nötige Gesamtprüfungen

Reviewer prüft besonders
- bekannte Fehlerrichtung dieses Tasks

Eskalation wenn
- Quelle widersprüchlich
- neue Fachentscheidung nötig
- Taskgrenze überschritten werden müsste
```

Das ist wesentlich wirksamer als lange Aufgabenprosa.

**Wichtig:** Ein Umsetzungstask sollte nicht „eine normative Aussage“ bedeuten. Das war für den Testabdeckungsabgleich sinnvoll. Für Umsetzung ist die bessere Größe:

> **ein kohärenter, einzeln prüfbarer Diff mit einem klaren Grund.**

Sonst erzeugst du zu viele winzige Änderungen und neue Koordinationsarbeit.

---

# Phase 1 – `zustand.md` einmal auf das neue Go-live-Ziel bringen

**Das passiert vor der Übertragung nach `bd`.**

Ich würde dort keine neue große Planung hineinschreiben. Es braucht nur eine neue Steuerregel:

> **Erster Go-live:** Pages PM ist für einen Einzelbenutzer zur dauerhaften Verwaltung echter Projekte und Vorgänge benutzbar. Vorher werden alle bekannten Änderungen abgeschlossen, deren spätere Umsetzung den produktiven Bestand grundlegend umformen oder eine größere Datenmigration verlangen würde. Zusätzliche Testtiefe, Dokumentationsverbesserungen und additive Funktionen dürfen nach Go-live folgen, soweit dadurch keine bekannte strukturelle Bestandsumwandlung aufgeschoben wird.

Danach werden die bestehenden Abschnitte **nicht entfernt**, sondern jeweils geteilt:

| Bereich        | **Vor Go-live**                                                                    | **Nach Go-live**                                                             |
| -------------- | ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Audit/P-010    | Umsetzung + kritischer Nachweis abschließen                                        | restlicher systematischer Abdeckungsabgleich, risikoarme Randfälle           |
| Hierarchie     | `parent_id` vollständig durch Objektgraph ersetzen; alle Dateninvarianten erhalten | zusätzliche Graph-/Diagnosetests und Komfortabfragen                         |
| Ein-Schreiber  | minimale verbindliche Semantik + technischer Mechanismus + Nebenläufigkeitstest    | weitere Robustheits-/Diagnosetests                                           |
| Lebensläufe    | bekannte Rückwege, Wiederaufnahme, Regel 20, `finished_at`, Abschlussfälle         | weniger riskante Matrix-/Randfälle                                           |
| `pm.objects`   | kleinste P-011-Sicht für den echten Vorgangsweg                                    | Erweiterung bei weiteren Facharten                                           |
| `write-sql.sh` | vorgesehener realer Einzelbenutzer-Schreibweg                                      | Komfortwerkzeuge/API                                                         |
| Dokumentation  | **keine falsche Aussage**, Installation und realer Gebrauch verständlich           | sprachliche Verfeinerung, zusätzliche Beispiele, vertiefter Kohärenzabgleich |
| Tests          | kritische Invarianten + bestehende Suite grün + E2E                                | systematischer Restabgleich aller testbaren Normsätze                        |
| E2E            | vollständiger echter Vorgangsfall                                                  | weitere reale Lebensläufe                                                    |

Die Hierarchie bleibt zwingend vor Go-live: `issues.parent_id` soll ausdrücklich verschwinden und Hierarchie, Kardinalität, Selbstbezug und Zyklusfreiheit sollen über den gemeinsamen Objektgraphen laufen; Regel 20 und Eposregeln müssen dabei erhalten bleiben. 

Das ist genau die Art Änderung, die du **nicht nach produktiven Daten** verschieben solltest.

---

# Phase 2 – eine einzige interaktive Planungssitzung

Erst jetzt kommt der starke Planer-Agent.

Sein Auftrag ist nicht:

> „Mach Schritt 5.“

sondern ungefähr:

```text
Lies zustand.md vollständig sowie die dort genannten maßgeblichen
Abschnitte aus product_spec.de.md, system_design.de.md und
development_guidelines.de.md.

Überführe die offene Arbeitsfolge in einen bd-Arbeitsgraphen.

Regeln:
1. Trenne innerhalb jedes Bereichs PRE-Go-live und POST-Go-live.
2. PRE enthält nur Arbeit, deren Aufschub
   - produktive Daten strukturell gefährdet,
   - eine bekannte spätere Bestandsumwandlung verursacht,
   - den realen Einzelbenutzer-Vorgangsweg verhindert,
   - oder für dessen sichere Freigabe zwingend nötig ist.
3. Konkrete bereits bekannte POST-Restarbeit darf als blockierte Arbeit
   erhalten bleiben.
4. Vage spätere Funktionen bleiben in zustand.md, nicht in bd.
5. Offene Entscheidungen werden eigene HUMAN-Tasks.
6. Kein Umsetzungstask darf eine noch offene Entscheidung voraussetzen.
7. Jeder Umsetzungstask verwendet das festgelegte Task-Schema.
8. Abhängigkeiten so setzen, dass bd ready ausschließlich tatsächlich
   ausführbare Tasks liefert.
9. Nichts implementieren.
```

### Was in `bd` kommt

Ich würde gegenüber dem früheren Vorschlag leicht unterscheiden:

**Ja:** alle bereits **konkret bekannten** Arbeiten der gegenwärtigen Bereiche dürfen in den Graphen.

**Nein:** nicht der gesamte ferne Nach-Go-live-Fahrplan.

Also etwa:

```text
Go-live
├── Audit PRE
├── Hierarchie PRE
├── Ein-Schreiber PRE
├── Lebenslauf PRE
├── pm.objects PRE
├── write-sql PRE
├── Doku PRE
├── kritische Prüfung
└── E2E

Go-live abgeschlossen
├─blocks→ Audit POST – konkret bekannte Resttests
├─blocks→ Hierarchie POST – konkret bekannte Resttests
├─blocks→ Doku POST – konkret bekannte Restprüfung
└─blocks→ ...

NICHT JETZT IN bd:
Renderer
Sprint
beliebige weitere Facharten
allgemeine Parameterschicht
zweite Installation
```

Diese Dinge gehören weiterhin zum späteren Horizont. `zustand.md` sagt heute bereits: erst eigene Nutzung, dann Renderer; Sprint, weitere Facharten, Parameter und Fremdinstallationslösung folgen aus tatsächlichem Bedarf. 

## Dein erstes und wichtigstes Tor

Danach schaust **du nur auf den Graphen**, nicht auf Code:

```text
bd list
bd ready
Abhängigkeitsgraph
```

Dabei stellst du nur fünf Fragen:

```text
Ist etwas vor Go-live, das gefahrlos danach könnte?

Ist etwas nach Go-live, das produktive Daten später umbauen würde?

Hat ein Task eine versteckte Entscheidung?

Ist ein Task so groß, dass sein Diff nicht mehr als Einheit prüfbar wäre?

Kann ein Umsetzer anhand dieses Tasks objektiv wissen, wann er fertig ist?
```

Wenn das stimmt, darf der Ausführungslauf beginnen.

---

# Phase 3 – der autonome Standardlauf

Ab jetzt solltest du **normalerweise gar nichts tun**.

```text
1. Orchestrator nimmt genau einen ready-Task.

2. Umsetzer liest:
   - Task
   - ausdrücklich genannte Quellen
   - betroffenen Quelltext

3. Umsetzer erstellt den kleinsten vollständigen Diff.

4. Gezielte Tests laufen.

5. Reviewer erhält:
   - Task
   - maßgebliche Quellen
   - Diff
   - Testergebnisse

6. Reviewer antwortet genau mit:

   PASS

   oder

   CHANGES
   - konkrete Abweichung
   - verletztes Akzeptanzkriterium / Quelle
   - kleinste nötige Korrektur

   oder

   ESCALATE
   - welche Entscheidung nicht aus den Quellen ableitbar ist

7. Bei CHANGES:
   automatisch zurück zum Umsetzer.

8. Bei PASS:
   nötige Bereichsprüfungen laufen,
   Commit,
   Task schließen,
   nächster ready-Task.
```

Der Reviewer darf **keine Geschmacksverbesserungen** verlangen.

Also nicht:

> „Ich würde außerdem …“

sondern nur:

> „Akzeptanzkriterium 3 ist nicht erfüllt, weil …“

Das beseitigt einen großen Teil der Endlosschleifen zwischen Agenten.

## Automatische Schleife begrenzen

Nach beispielsweise **zwei erfolglosen Korrekturrunden derselben Beanstandung** sollte nicht Runde drei erfunden werden.

Dann:

```text
ESCALATE: Reviewer und Umsetzer konvergieren nicht.
```

Das ist ein guter Einsatz deiner Aufmerksamkeit: ein echter schwieriger Fall statt 20 normale Diffs.

---

# Phase 4 – harte Eskalationsregeln

Der Orchestrator soll dich **nur** rufen, wenn mindestens eines davon eintritt:

| Eskalationsgrund                                   | Beispiel                                               |
| -------------------------------------------------- | ------------------------------------------------------ |
| normative Quellen widersprechen sich               | Produktregel sagt A, Systementwurf setzt B voraus      |
| eine neue Fach-/Architekturentscheidung wird nötig | Lockmechanismus zeigt unbehandelten Semantikfall       |
| Umsetzung müsste den Taskumfang verlassen          | Hierarchietask verlangt unerwartet neues Projektmodell |
| bestehende Entscheidung müsste geändert werden     | Übergangsmatrix reicht technisch nicht                 |
| Reviewer und Umsetzer konvergieren nicht           | gleiche Beanstandung bleibt nach Korrekturen           |
| unerwartete spätere Datenmigration entsteht        | PRE/POST-Einstufung war falsch                         |
| Tests zeigen einen bereits vorhandenen Widerspruch | kein lokaler Fehler des Tasks                          |

**Nicht eskalieren:**

```text
Test muss ergänzt werden
kleiner SQL-Fehler
Kommentar verletzt §1.5
unnötige Duplikation
Namens-/Strukturfehler
Diff ist größer als nötig
bestehender Test muss angepasst werden
```

Dafür ist der Reviewer da.

---

# Phase 5 – konkrete Reihenfolge bis Go-live

Unter dem neuen Schnitt würde ich den ausführbaren Pfad so kurz machen:

```text
G0  Audit/P-010-Nacharbeiten schließen
    nur noch kritische normative Lücken

 ↓

G1  Vorgangshierarchie → object_relations
    parent_id weg
    allgemeine Graphregeln
    Vorgangsregeln erhalten

 ↓

G2  zentrale Ein-Schreiber-Regel
    minimaler Mechanismus
    sofortige Abweisung
    kritischer Nebenläufigkeitstest

 ↓

G3  Vorgangslebenslauf fertig
    ready → clarification
    in_review → in_progress
    discarded → clarification
    finished_at
    Regel-20-Fälle

 ↓

G4  minimales pm.objects

 ↓

G5  minimales write-sql.sh

 ↓

G6  Go-live-Doku
    nur:
    - keine falschen Aussagen
    - tatsächlicher Einzelbenutzerweg
    - betroffene Sprachfassungen kohärent
    - automatische Prüfungen grün

 ↓

G7  Freigabelauf
    vorhandene Gesamttests
    kritische neue Tests
    Referenzen
    Sprachstruktur

 ↓

G8  echter vollständiger Vorgangslebenslauf

 ↓

GO-LIVE
```

Der bestehende E2E-Meilenstein eignet sich dafür sehr gut: Projekt wählen, Vorgang anlegen, Pflichtschwellen durchlaufen, `depends_on` tatsächlich sperren und später freigeben, Kindvorgang verwenden, Elternabschluss prüfen, fehlgeschlagene Übergänge ohne Zustands-/Verlaufsänderung bestätigen und die Gegenstände über die gemeinsame Sicht finden. 

Das ist ein viel besseres **Go-live-Abnahmekriterium** als „jede normative Aussage besitzt bereits ihren maximalen Test“.

---

# Phase 6 – dein zweites Tor: Go-live

Hier würde ich dich noch **bewusst** im Ablauf lassen.

Der Orchestrator liefert nur:

```text
PRE-Go-live Tasks:       alle geschlossen
offene HUMAN-Entscheide: keine
Gesamtlauf:              grün
Dokumentationsprüfungen: grün
E2E:                     grün
POST-Go-live Tasks:      blockiert / nicht freigaberelevant
Arbeitsbaum:             sauber
```

Du musst dann **nicht alle Diffs nochmals lesen**.

Du prüfst nur:

1. Ist das tatsächlich der vereinbarte Einzelbenutzer-Go-live?
2. Gibt es irgendeine bekannte strukturelle Änderung, die jetzt schon produktive Daten betreffen würde?
3. Ist der echte E2E-Fall überzeugend durchgelaufen?

Dann Go-live.

---

# Phase 7 – unmittelbar danach

Der erste produktive Pages-PM-Vorgang sollte dann möglichst **die weitere Pages-PM-Arbeit selbst** sein. Das ist ohnehin der bestehende Plan nach Go-live. 

Danach würde ich einen neuen Planerlauf machen:

```text
reale Nutzung seit Go-live lesen
+
konkrete POST-Tasks aus dem alten Graphen
+
Fehler/Umständlichkeiten aus echter Verwendung
        ↓
neuer Prioritätsgraph
```

Die Reihenfolge sollte dann ungefähr sein:

| Vorrang    | Nach Go-live                                                            |
| ---------- | ----------------------------------------------------------------------- |
| **P0**     | tatsächliche Daten-/Betriebsfehler aus der Nutzung                      |
| **P1**     | aufgeschobene Integritäts-/Normtests mit noch relevantem Risiko         |
| **P1**     | falsche oder hinderliche Dokumentation                                  |
| **P2**     | restliche Testtiefe und Doku-Härtung                                    |
| **P2**     | Renderer                                                                |
| **danach** | Verantwortung/P-004 bzw. weitere Fachfunktion nach tatsächlichem Bedarf |
| **später** | Sprint, weitere Facharten, Parameter, zweite Installation               |

Damit werden auch die ersten Monate nicht zu einem zweiten großen „MVP fertigbauen“, sondern zu **beobachtungsgetriebener Härtung**.

---

# Was sich für dich praktisch ändert

Der bisherige Ablauf war ungefähr:

```text
Agent setzt um
→ du liest Diff
→ du findest konzeptionelle Abweichung
→ Agent korrigiert
→ du liest wieder
→ nächster Diff
```

Der neue:

```text
DU:
einmal Go-live-Schnitt festlegen

PLANER:
Graph erzeugen

DU:
Graph prüfen

ORCHESTRATOR:
Umsetzer ↔ Reviewer
Umsetzer ↔ Reviewer
Umsetzer ↔ Reviewer
...

DU:
nur echte Entscheidungen / Sackgassen

ORCHESTRATOR:
E2E + Freigabebericht

DU:
Go-live
```

**Das ist für Pages PM wahrscheinlich der entscheidende Produktivitätsgewinn.** Nicht ein „stärkerer Umsetzungsagent“, sondern dass der starke Agent, den du bisher als laufende Kontrollinstanz benutzt hast, eine **explizite Reviewer-Rolle mit festen Kriterien** bekommt und du selbst aus dieser Schleife herauskommst.

Ich würde daher in dieser Reihenfolge fortfahren:

**1. neue Agentenumgebung einrichten → 2. `zustand.md` einmal auf den neuen Go-live-Schnitt bringen → 3. Planer erzeugt `bd` → 4. du prüfst den Graphen → 5. erster autonomer Lauf zunächst mit G0/Audit als Probe → 6. wenn der sauber durchläuft, G1–G8 ohne laufende Diff-Prüfung durch dich.**

Das gibt dir gleichzeitig einen Sicherheitsmechanismus: Der erste autonome Lauf ist der fast abgeschlossene Audit-Schritt und nicht sofort der große Hierarchieumbau.

---

