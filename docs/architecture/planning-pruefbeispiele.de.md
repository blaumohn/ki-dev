# Prüfbeispiele und Versuchskriterien: begrenzter Designnotizen-Versuch

Stand: 2026-09-15. Ergebnis von `ki-dev-ablauf-urq.2`. Dieser Vertrag setzt
`ki-dev-ablauf-urq.1` (`docs/architecture/planning-verarbeitungsvertrag.de.md`)
voraus und bindet ausschließlich den begrenzten Versuch in `ki-dev-ablauf-urq`.
Die hier festgelegten Beispiele, Zahlen und Grenzen sind vorläufige
Versuchsentscheidungen. Sie dürfen nach Sichtung des Laufergebnisses
(`urq.6`) nicht gelockert werden (siehe `urq.1` Nicht-Umfang).

Quellen: `.loope/runs/0002-hier-ist-eine-vorschlage-ziel-bd/report.md`
(Vorgang 2); Quellen-Beads ki-dev-ablauf-9407, ki-dev-ablauf-phdp, ki-dev-ablauf-74lc und ki-dev-ablauf-uxdk sowie Codex-Sitzung `01a09aef`.

## Prüfbeispiel-Set

Jedes Beispiel nennt: Quelle (echt oder konstruiert), erwartetes Ergebnis,
und welche der in `urq.1` benannten Regeln es prüft. „Echt“ heißt: exaktes
Zitat mit Datei und Zeilen-/Nachrichtenbereich, unverändert aus der Quelle.
„Konstruiert“ heißt: von Hand für diesen Versuch geschrieben, weil die
Quellen den Fall nicht eindeutig genug enthalten; solche Fälle sind
ausdrücklich als `KONSTRUIERT` markiert und dürfen nicht als tatsächliche
Projektaussage in den Bestand geraten.

### PB-1 — Bedingte Rücknahme / Widerspruch (echt)

Quelle: `bd:ki-dev-ablauf-phdp#L102` (Planerausgabe 1) und
`:106` (Planerausgabe 2).

> Zeile 102: „Ich würde deshalb **Ralphex jetzt nicht aus dem Bootstrap
> entfernen**, aber die Annahme … als neue offene Planungsentscheidung
> markieren.“
> Zeile 106: „Ja. Unter dieser Voraussetzung würde ich **Ralphex aus dem
> Bootstrap entfernen**.“

Erwartung: Beide Aussagen bleiben als eigene, bedingungstragende Anteile
erhalten (Erhaltungsregel). Zeile 106 ist keine unbedingte Rücknahme von
Zeile 102, sondern an die in Zeile 102 offen gelassene Bedingung gebunden;
die Modalität „bedingt“ darf beim Verarbeiten nicht zu einer unbedingten
Entscheidung verschärft werden. Eine automatische Verkettung „neuerer Anteil
ersetzt älteren“ ist unzulässig (Zuordnung/Operation getrennt).
Fehlerklasse bei Verstoß: **kritisch** (Modalitätsverlust).

### PB-2 — Verwerfen und Ersetzen eines Plans (echt)

Quelle: `bd:ki-dev-ablauf-phdp#L358`.

> „Ich würde daher den bisherigen „Bootstrap Stufe 1–4“-Plan weitgehend
> **verwerfen** und durch etwas wie **„Minimal-Go-live von ki-dev“**
> **ersetzen**.“

Erwartung: Der bestehende „Bootstrap Stufe 1–4“-Knoten wird nicht gelöscht
(Historie wächst nur; siehe `planning-graph.de.md`), sondern über eine
typisierte Beziehung (z.B. `ersetzt_durch`) mit einem neuen Knoten
„Minimal-Go-live von ki-dev“ verbunden. Prüft: Zuordnung vs. Operation,
Erhaltungsregel, Beziehungstypisierung.
Fehlerklasse bei Verstoß: **kritisch**, falls der alte Knoten gelöscht statt
verknüpft wird; **sonstig**, falls nur der Beziehungstyp unpräzise ist.

### PB-2b — Verzweigte Ersetzung (KONSTRUIERT)

Die Quellen enthalten an dieser Stelle nur eine lineare Ersetzung (PB-2:
ein alter Knoten, ein neuer Knoten). Der in `urq.2` namentlich verlangte
Fall „verzweigte Ersetzung“ (ein Knoten wird durch **mehrere** parallele
Nachfolgeknoten ersetzt) findet sich nicht eindeutig in den Quellen und ist
daher konstruiert, unter Wiederverwendung desselben Quellankers wie PB-2
(`bd:ki-dev-ablauf-phdp#L358`) für einen strukturell
gültigen Quellenverweis:

> `KONSTRUIERT`: „Der bisherige „Bootstrap Stufe 1–4“-Plan wird nicht durch
> einen einzelnen Nachfolgeplan ersetzt, sondern in zwei parallele
> Nachfolgepläne aufgespalten: **„Minimal-Go-live von ki-dev“** und
> **„Design-Notizen-Pilot als separater Versuch“**.“

Erwartung: Der alte Knoten „Bootstrap Stufe 1-4“ bleibt erhalten
(Erhaltungsregel) und erhält **zwei** eigenständige `ersetzt_durch`-Kanten
zu zwei unterschiedlichen neuen Zielknoten, je mit eigener Kennung und
eigenem Quellenbeleg. Beide Zweige müssen einzeln erhalten bleiben; eine
Zusammenführung der beiden Ziele zu einem Knoten oder einer Kante ist
unzulässig. Prüft: Zuordnung vs. Operation bei Mehrfachzielen aus einem
Quellknoten, Erhaltungsregel, Beziehungstypisierung.
Fehlerklasse bei Verstoß: **kritisch**, falls ein Zweig beim Verarbeiten
verloren geht oder beide Ziele fälschlich zusammengeführt werden;
**sonstig**, falls nur ein Beziehungstyp unpräzise ist (analog PB-2).

### PB-3 — Bereichsübergreifende Dublette (echt)

Quelle: `bd:ki-dev-ablauf-9407#L503-L695` (Ralphex als
Ausführungs- und Reviewmaschine im Bootstrap) und
`bd:ki-dev-ablauf-phdp#L102-L106` (PB-1, Ralphex-Verbleib als
offene Entscheidung).

Erwartung: Beide Passagen betreffen dieselbe fachliche Einheit („Ralphex im
Bootstrap“), liegen aber an unterschiedlichen Orten (Ausführungsdetail vs.
Umfangsentscheidung). Die Kandidatensuche muss den Bezug bereichsübergreifend
finden, auch wenn `001` lokal keine Nachbarschaft zu `002` hat
(„begrenzt aber nicht die Kandidatensuche“, siehe `urq.1`). Prüft: die
bereichsübergreifende Suchregel; das ist der in `urq.2` NOTES benannte
Pflichtfall für eine Suchtrefferquote.
Fehlerklasse bei Verstoß (Bezug nicht gefunden): **kritisch** (Suchfehler).

### PB-4 — LangGraph-Fall L: Empfehlung → Entscheidung → Zurückstellungsvorschlag (echt)

Quellen, in dieser Reihenfolge:

1. Empfehlung: `bd:ki-dev-ablauf-74lc#L3315` — „**LangGraph
   ist dabei am nächsten an deinem Orchestrator.**“
2. Entscheidung: `bd:ki-dev-ablauf-uxdk#L52` — „Ja. **Für den
   eigentlichen `ki-dev loop` ist LangGraph sehr wahrscheinlich bereits die
   passendere Grundlage** … Aber LangGraph ist dabei **der
   Orchestrator-Unterbau**, nicht das fertige `ki-dev`.“
3. Zurückstellungsvorschlag: `codex:01a09aef`,
   Nachricht 59 (Zeile 60) — „**Entscheidung:** LangGraph ist als
   Orchestrierungsbasis vorgesehen. **Vorschlag:** Den eigenen Loop
   vorläufig zurückstellen und Loope als Bootstrap verwenden.“

Zusätzlicher Beleg für die Modalität des dritten Beitrags:
`codex:01a09aef` Nachricht 58 (Zeile 59) hält ausdrücklich fest,
dass eine frühere Rückmeldung die Zurückstellung fälschlich als „beschlossene
Rücknahme“ zugespitzt hatte und korrigiert: „die Zurückstellung [war]
ausdrücklich ein Entscheidungsvorschlag, noch keine Änderung des
verbindlichen Plans.“

Erwartung: Im Ergebnis stehen **nebeneinander**: die Entscheidung „LangGraph
als Orchestrierungsbasis“ (aus Quellen-Bead ki-dev-ablauf-uxdk) und der **Vorschlag** „eigenen
Loop zurückstellen, Loope als Bootstrap“ (aus Codex-Sitzung 01a09aef) — nicht als
beschlossene Rücknahme der Entscheidung. Dies ist der in `urq.1` genannte
Prüffall für Modalitätstreue und zugleich Testfall für Vorgang 7 (Frage:
„Ließ sich die Zurückstellung durchgängig als Vorschlag erkennbar halten?“).
Fehlerklasse bei Verstoß: **kritisch** (Modalitätsverlust, siehe PB-1).

### PB-5 — Rücknahme einer Entscheidung (KONSTRUIERT)

Die Quellen enthalten keine eindeutige, unbedingte Rücknahme einer zuvor
beschlossenen Anforderung (die einzigen Kandidaten sind PB-1, bedingt, und
PB-4, ein Vorschlag statt einer Rücknahme). Daher konstruierte Testeingabe:

> `KONSTRUIERT`: „Die in Quellen-Bead ki-dev-ablauf-phdp (Zeile 106) beschlossene Entfernung von
> Ralphex aus dem Bootstrap wird aufgehoben. Ralphex bleibt endgültig Teil
> des Bootstrap-Vorgehens; die Bedingung aus Zeile 102 gilt als nicht
> eingetreten.“

Erwartung: Neue Revision der betroffenen Einheit bzw. neue Kante
`hebt_auf` mit Zielverweis auf die durch PB-1/PB-2 entstandene Kante/Version;
Quellenverweis zeigt eindeutig auf die konstruierte Testpassage, nicht auf
eine echte Sitzung. Prüft: Rücknahme-Verarbeitung, Abdeckungsnachweis-Pflicht
(„bereits enthalten“ hier unzulässig, da inhaltlich neu).
Fehlerklasse bei Verstoß: **kritisch**.

### PB-6 — Raumumbau mit mitwandernden Anteilen (KONSTRUIERT)

Motiviert durch die in `codex:01a09aef` Nachricht 47
zitierte offene Frage „F₁ → F₂: wandern Abschnitte mit?“. Konstruierte
Testeingabe:

> `KONSTRUIERT`: „Der bisherige Bereich `planungsspeicher` wird in
> `planungsspeicher/modell` und `planungsspeicher/agentenablauf` aufgeteilt.
> Die bestehende Einheit zur Unveränderlichkeit gehört ab jetzt zu
> `planungsspeicher/modell`.“

Erwartung: Die vorgeprüfte Arbeitskarte (Raumumbau-Regel, `urq.1`) markiert
`planungsspeicher/modell` und `planungsspeicher/agentenablauf` als
betroffen; die Kandidatensuche bleibt bereichsübergreifend und darf die
umgezogene Einheit nicht wegen des alten Ortsstrings verfehlen. Ergebnis:
neue Revision der Einheit mit `location: planungsspeicher/modell`; keine
neue Identität. Prüft: Raumumbau-Regel (Auswertungsfrage aus `urq.1`),
Ortsfeld als Suchhinweis statt Identität.
Fehlerklasse bei Verstoß: **sonstig** (Lokalisierungsfehler ohne
Bedeutungsverlust), außer die Einheit wird dabei verdoppelt — dann
**kritisch**.

### PB-7 — Erhaltung von Vorschlag, Beispiel und Bedingung bei „bereits enthalten“ (echt)

Quelle: `codex:01a09aef`, Nachricht 49 (Zeile 50),
Tabelle „Was ich übernehme — mit einigen Präzisierungen“, Zeile zu
„KI-Verarbeitung“: „Jede relevante Quellpassage muss einem Ergebnis
zugeordnet sein: übernommen, präzisiert, **bereits enthalten** oder
ausdrücklich ausgeschlossen.“

Erwartung: Eine Einstufung „bereits enthalten“ für diese Passage ist nur
zulässig, wenn eine bestehende Knoten-/Kantenrevision konkret dieselbe
Vier-Wege-Unterscheidung (übernommen/präzisiert/bereits enthalten/
ausgeschlossen) bereits trägt — sonst ist „präzisiert“ oder „neu“ die
richtige Operation (Abdeckungsnachweis-Pflicht, `urq.1`).
Fehlerklasse bei Verstoß: **kritisch** (unbelegtes „bereits enthalten“).

## Suchtrefferquote

Vorab festgelegt, gemessen im Lauf (`urq.6`):

- Für jede verarbeitete Passage wird zusätzlich zu den angezeigten
  Kandidaten eine Zufallsstichprobe von mindestens 5 Einheiten außerhalb der
  angezeigten Kandidaten gezogen und im Review mitgeprüft (Blindprobe für
  falsch-negative Kandidatensuche).
- Trefferquote = Anteil der PB-1 bis PB-7 (sowie aller im Lauf tatsächlich
  vorliegenden echten Bezüge), bei denen der korrekte Bezug **innerhalb**
  der angezeigten Kandidaten lag.
- Messpunkte nach Bestandsgröße: nach 3, nach 6 und nach 9 verarbeiteten
  Sitzungen (bzw. Snapshots) wird die Trefferquote auf dem bis dahin
  verarbeiteten Bestand erhoben.
- **NICHT BESTANDEN**, wenn die Trefferquote an irgendeinem Messpunkt unter
  70 % fällt, **oder** wenn sie zwischen zwei aufeinanderfolgenden
  Messpunkten um mehr als 20 Prozentpunkte abfällt (als „nicht tragfähiger
  Abfall“ gewertet, unabhängig vom absoluten Stand).

## Bestandswachstum für die Messung

Offene Entscheidung aus `urq.2`-NOTES aufgelöst: Ein einzelner begrenzter
Lauf verarbeitet zu wenig, um Trefferquote über Bestandsgrößen zu messen.
Der Lauf (`urq.6`) bereitet daher vor dem eigentlichen begrenzten
Testschritt einen größeren Ausgangsbestand vor, indem er die Snapshots
`001`–`008` regulär (nicht als Testschritt, sondern als normale, im
Kontrollprotokoll mitgeführte Vorverarbeitung) einarbeitet. Der eigentliche,
budgetierte und bewertete Testschritt verarbeitet danach `009` und `010`
gegen diesen vorbereiteten Bestand. Trefferquoten-Messpunkte (3/6/9) fallen
in die Vorbereitung; die abschließende Bewertung (PASS/FAIL) des
Testschritts selbst bezieht sich auf `009`/`010`.

## Erwartete Inhalte und unzulässige Verluste

Erwartet: für jede in PB-1 bis PB-7 (einschließlich PB-2b) benannte Passage
ein im Delta nachvollziehbarer Anteil mit Zuordnung und Operation (siehe
Vorgang 4). Unzulässig: Verlust einer Bedingung, Ausnahme, eines Beispiels
oder Vorschlags (Erhaltungsregel); Verschärfung oder Abschwächung einer
Modalität (PB-1, PB-4); Löschen statt Verknüpfen bei Ersetzung (PB-2);
Verlust oder Zusammenführung eines Zweigs bei verzweigter Ersetzung (PB-2b);
unbelegtes „bereits enthalten“ (PB-7); übersehene bereichsübergreifende
Dublette (PB-3).

## Fehlerklassen

- **Modellfehler**: das Datenmodell (`urq.3`) kann den Fall strukturell
  nicht darstellen (schon in `urq.4` zu beheben, nicht erst im Lauf).
- **Interpretationsfehler**: der Abflachungsagent ordnet richtig lokalisiert
  zu, trifft aber die falsche inhaltliche Operation oder verliert Bedeutung.
- **Suchfehler**: der korrekte Bezug lag außerhalb der angezeigten
  Kandidaten (siehe Trefferquote oben).
- **Reviewfehler**: der Review bestätigt einen Entwurf, der gegen eine der
  obigen Regeln verstößt.

**Kritisch** sind: jeder Modellfehler; jeder Interpretationsfehler mit
Bedeutungs- oder Modalitätsverlust (PB-1, PB-4, PB-7); jeder Suchfehler bei
PB-3; jeder verlorene oder fälschlich zusammengeführte Zweig bei PB-2b.
**Sonstig** sind: Lokalisierungsungenauigkeiten ohne Bedeutungsverlust
(PB-6, sofern keine Verdopplung); unpräzise, aber nicht falsche
Beziehungstypen (PB-2, PB-2b).

## Bestehens- und Nichtbestehenskriterien (Vorgang 6)

**BESTANDEN**, wenn alle der folgenden Bedingungen gelten:

1. Kein kritischer Fehler bei PB-1 bis PB-5, PB-2b und PB-7 im budgetierten
   Testschritt (`009`/`010`).
2. Die Suchtrefferquote unterschreitet an keinem Messpunkt die oben
   genannten Grenzen.
3. Die Doppelverarbeitung (siehe unten) zeigt keine widersprüchliche
   Zuordnung für dieselbe Passage.

**NICHT BESTANDEN**, wenn mindestens ein kritischer Fehler auftritt oder eine
Trefferquotengrenze verletzt wird, der Lauf aber methodisch korrekt
durchgeführt wurde (siehe `urq.6` NOTES: ein korrekt durchgeführter negativer
Versuch bleibt gültig).

**UNGÜLTIG**, wenn eine der folgenden Ungültigkeitsbedingungen zutrifft:
unerlaubter Zugriff des Abflachungsagenten auf historische Deltas oder das
Roharchiv; Kenntnis dieses Dokuments (der hier festgelegten erwarteten
Ergebnisse) durch den Abflachungsagenten oder den regulären Review vor bzw.
während des Laufs; Überschreiten des Korrektur- oder Laufbudgets ohne dies
offen als Abbruch zu dokumentieren; nachträgliches Verändern dieses
Dokuments nach Sichtung eines Zwischenergebnisses.

## Korrektur- und Laufbudget

Je Passage höchstens eine Korrekturrunde zwischen Entwurf und Review vor
Übernahme (siehe `urq.1`, Korrekturrunden-Regel); der budgetierte
Testschritt (`009` + `010`) läuft in höchstens zwei Sitzungen des
Abflachungsagenten. Wird das Budget überschritten, ist der Lauf ab diesem
Punkt abzubrechen und als methodisch korrekt durchgeführter, aber
budgetüberschreitender Versuch zu protokollieren — nicht heimlich
fortzusetzen.

## Doppelverarbeitung

Snapshot `002` (bereits Teil der Vorbereitung, siehe oben) wird zusätzlich
ein zweites Mal, unabhängig vom ersten Durchlauf, verarbeitet (gleicher
Ausgangsbestand vor `002`, kein Rückgriff auf das erste Ergebnis). Verglichen
werden: Lokalisierung (`location`), Zuordnung (Ziel-Einheiten) und
Anteilsliste (Vollständigkeit der Zerlegung) beider Durchläufe für PB-1 und
PB-2. Abweichungen sind eine Messung der Stabilität, keine Korrekturrunde
eines der beiden Durchläufe.

## Nicht-Umfang dieses Dokuments

Keine Umsetzung des Datenmodells (`urq.3`/`urq.4`) oder des Agentenlaufs
selbst (`urq.5`/`urq.6`). Die hier festgelegten Zahlen (70 %, 20
Prozentpunkte, 5 Stichproben, zwei Sitzungen Budget) sind vorläufige
Versuchsentscheidungen, keine allgemeinen Qualitätsziele für ein späteres
Produktivsystem.
