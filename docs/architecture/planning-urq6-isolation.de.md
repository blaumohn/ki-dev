# urq.6: Kontaminationsbefund und Blindheits-Protokoll für den unabhängigen Durchlauf

Stand: 2026-09-15. Bezug: `ki-dev-ablauf-urq.6` (Unabhängigen Durchlauf
ausführen), `ki-dev-ablauf-urq.7` (Auswertung). Setzt
`docs/architecture/planning-pruefbeispiele.de.md` (Bestehens-/
Nichtbestehens-/Ungültigkeitskriterien) und
`docs/architecture/planning-verarbeitungsvertrag.de.md` voraus.

## Befund

`urq.6` blieb über mehrere `.loope`-Läufe (0012, 0013, 0014) unerledigt,
obwohl `urq.5` (Agenten-/Reviewablauf, `src/ki_dev/pilot/workflow.py`,
`search.py`, `log.py`) seit Lauf 0014 vollständig implementiert
und getestet ist. Grund ist keine fehlende Infrastruktur, sondern eine
strukturelle Ungültigkeitsbedingung: `planning-pruefbeispiele.de.md` legt
fest (Abschnitt „Bestehens- und Nichtbestehenskriterien“, UNGÜLTIG-Fall):

> Kenntnis dieses Dokuments (der hier festgelegten erwarteten Ergebnisse)
> durch den Abflachungsagenten oder den regulären Review vor bzw. während
> des Laufs.

Jeder `implementer`/`reviewer`-Schritt dieser `.loope`-Pipeline arbeitet
laut eigenem Auftrag „nur aus der Anforderung und verfügbaren Design-/
Review-Artefakten“ — das schließt in der Praxis den gesamten Projektbaum
ein, also auch `planning-pruefbeispiele.de.md` mit PB-1 bis PB-7 und den
erwarteten Ergebnissen. Sobald ein Implementer- oder Reviewer-Schritt diese
Datei gelesen hat (was zur normalen Orientierung im Repository gehört),
ist er für die Rollen „Abflachungsagent“ und „regulärer Review“ in `urq.6`
dauerhaft disqualifiziert — jeder von ihm erzeugte Durchlauf wäre nach der
eigenen Definition `UNGÜLTIG`, unabhängig vom inhaltlichen Ergebnis.

Das erklärt den wiederholten Leerlauf: die Empfehlung früherer Implementer-
Schritte, „der nächste Loop-Schritt solle den Versuch ausführen“, löst das
Problem nicht, weil der nächste Schritt derselben Pipeline denselben
Repository-Kontext erhält und damit ebenso kontaminiert ist.

## Notwendige Trennung für einen gültigen Lauf

`urq.6` verlangt drei Rollen mit unterschiedlichem, nicht überlappendem
Wissensstand:

1. **Abflachungsagent-Sitzung(en)** — frische Sitzung ohne Vorgeschichte,
   die ausschließlich den Rückgabewert von `pilot.workflow.build_context()`
   erhält (freigegebene neue Passagen, lokalisierter Bestand, Typregister)
   sowie die *prozeduralen* Regeln aus `planning-verarbeitungsvertrag.de.md`
   (Zuordnung/Operation getrennt, Abdeckungsnachweis-Pflicht, Erhaltungs-
   und Modalitätsregel) — in neutraler Formulierung, ohne PB-1 bis PB-7 und
   ohne deren erwartete Ergebnisse zu zitieren oder erkennbar zu machen.
   Diese Sitzung darf `planning-pruefbeispiele.de.md` nie gelesen haben.
2. **Reguläre Review-Sitzung** — ebenfalls frisch, erhält den Entwurf plus
   das tatsächliche Quellzitat und den betroffenen Ausgangsbestand (siehe
   `urq.5`-Umfang „Review prüft Quelle, betroffenen Ausgangsbestand und
   Ergebnis“), aber ebenfalls nicht die erwarteten Ergebnisse aus
   `planning-pruefbeispiele.de.md`.
3. **Unabhängiger Vergleich (Auswertung, nach Laufende)** — wird von einer
   Sitzung mit Kenntnis der eingefrorenen Kriterien durchgeführt (z.B. dieser
   Controller), erst *nachdem* die Einträge aus 1. und 2. bereits
   unveränderlich im Kontrollprotokoll (`pilot/log.py`, Anhängemodus)
   stehen. Diese Rolle vergleicht Kontrollprotokoll gegen PB-1–PB-7,
   berechnet die Suchtrefferquote und das Ergebnis
   (BESTANDEN/NICHT BESTANDEN/UNGÜLTIG). Sie darf die Einträge aus 1./2.
   nicht mehr verändern, nur auswerten.

Schritte 1 und 2 können nicht als gewöhnliche Schritte dieser
`.loope`-Anforderungspipeline laufen, solange deren Prompt-Aufbau
routinemäßig den vollen Projektbaum einschließt. Sie benötigen eine
gezielt zusammengestellte, minimale Eingabe (z.B. eine eigenständige
Subagent-Anfrage mit handverlesenem Prompt) statt der Standard-Anweisung
„Work only from the requirement and available design/review artifacts“.

## Stand dieses Dokuments

Dieser Lauf (und alle vorherigen `implementer`-Schritte ab Lauf 0012) haben
`planning-pruefbeispiele.de.md` bereits gelesen und sind damit für die
Rollen 1./2. oben verbraucht. Dieses Dokument enthält bewusst keine
erfundenen `urq.6`-Ergebnisse — ein tatsächlicher Durchlauf muss aus einer
Sitzung ohne diese Vorgeschichte gestartet werden, mit exakt dem in Rolle 1
bzw. 2 beschriebenen Kontext, und seine Kontrollprotokoll-Ausgabe
anschließend gegen `planning-pruefbeispiele.de.md` ausgewertet werden
(Rolle 3, `urq.7`).

## Nicht-Umfang

Keine Ausführung des budgetierten Testschritts (`009`/`010`) von `urq.6`
selbst. Keine Änderung der in `planning-pruefbeispiele.de.md` eingefrorenen
Zahlen oder Kriterien.

## Nachtrag (Lauf 0017): Vorbereitung geprüft statt nur behauptet

Hinweis zur Veröffentlichung: Die Quellen der Sitzungen 001–010 sind lokale
Planungsquellen mit persönlichen Gesprächsinhalten und nicht veröffentlicht.
Skripte und `docs/architecture/urq6-run/` nennen sie mit ortsunabhängiger
Quellen-ID (`bd:<Quellen-Bead>` oder `codex:<Sitzungs-ID>`) statt mit lokalem
Pfad; Zeilen und Prüfsummen bleiben die der aufgezeichneten Kopie. Die
Hash-Kette des aufgezeichneten Laufs ist damit nicht mehr prüfbar.
`scripts/urq6_prep.py` und `scripts/urq6_test.py` brechen vor jedem Lesen mit
Exitcode 1 ab, solange die Auflösung ID → Datei fehlt
(`ki-dev-ablauf-xy78.2.1`, Entscheidung `ki-dev-ablauf-guq`).

Der vorangegangene Implementer-Schritt (Lauf 0015, Iteration 2) hat neben
diesem Dokument bereits `scripts/urq6_prep.py` sowie
`docs/architecture/urq6-run/` erzeugt (Sitzungen 001–008, siehe
`planning-pruefbeispiele.de.md`, Abschnitt „Bestandswachstum für die
Messung“: die reguläre Vorverarbeitung vor dem eigentlichen budgetierten
Testschritt). Der Schritt selbst ist an einem Timeout gestorben, bevor er
das Ergebnis bewerten konnte; die Review-Blockade in Lauf 0015 bemängelte
zurecht, dass ein Isolationsdokument allein weder Lauf, Doppelverarbeitung,
Suchtrefferquote noch Auswertung ersetzt. Dieser Nachtrag prüft, was von
diesem Vorbereitungsschritt tatsächlich Bestand hat, statt es erneut nur zu
behaupten:

- Alle 8 `_delta-*.json` und alle 8 `store/*.json` sind valides JSON; die
  Delta-Kette ist vollständig (Sitzungen 1–8, `state["nodes"]` wächst
  monoton von 2 auf 9 Einheiten).
- `control-log.jsonl` enthält 35 valide JSONL-Zeilen.
- Das Skript ist deterministisch (fester `RNG_SEED`): eine erneute
  Ausführung in einer frischen Kopie des Repos erzeugt byte-identische
  `_delta-*.json`/`store/*.json`/`control-log.jsonl` (geprüft per
  `diff -rq`) und läuft in unter 0,1 s — der 600-s-Timeout aus Lauf 0015
  kam nicht vom Skript selbst, sondern von einem anderen Teil des
  Implementer-Schritts.
- Suchtrefferquote (Vorbereitungssitzungen 1–8, gemäß
  `planning-pruefbeispiele.de.md` fallen die Messpunkte 3/6 in die
  Vorbereitung): nach 3 Sitzungen keine fällige Referenz (0/0, nicht
  auswertbar); nach 6 Sitzungen 1/1 (100 %). Beide Treffer (Sitzung 4 →
  `bootstrap-ausfuehrung-ralphex`, Sitzung 8 → `langgraph-empfehlung`)
  lagen innerhalb der angezeigten Kandidaten.

Damit ist die Vorbereitung (Rolle: reguläre, nicht-blinde Infrastruktur,
kein Abflachungs- oder Reviewschritt) verifiziert und reproduzierbar,
nicht bloß Timeout-Datenmüll.

### Was weiterhin fehlt (nicht in diesem Schritt erledigt)

Die drei Punkte aus der Review von Lauf 0015 bleiben offen, weil sie den in
diesem Dokument beschriebenen blinden Abflachungs-/Reviewschritt
voraussetzen, den dieser (bereits kontaminierte) Implementer-Schritt nicht
selbst durchführen darf:

1. **Budgetierter Testschritt** (`009`/`010`, PB-1 bis PB-7 gegen den jetzt
   verifizierten Bestand aus 1–8).
2. **Doppelverarbeitung** von Snapshot `002` (zweiter, unabhängiger
   Durchlauf ohne Rückgriff auf das erste Ergebnis).
3. **Trefferquoten-Messpunkt „nach 9 Sitzungen“** und die abschließende
   `urq.7`-Auswertung (PASS/NICHT BESTANDEN/UNGÜLTIG) — beide setzen 1./2.
   voraus.

Dies erfordert eine frische Sitzung ohne Kenntnis von
`planning-pruefbeispiele.de.md`, mit genau dem in Rolle 1/2 oben
beschriebenen minimalen Kontext (z.B. eine gezielt zusammengestellte
Subagent-Anfrage). Das bewusst nicht in diesem Schritt zu starten, statt es
unter Zeitdruck zu improvisieren, vermeidet den in Lauf 0015 aufgetretenen
Timeout und vermeidet vor allem, Rollen 1/2 aus Versehen ein weiteres Mal
zu kontaminieren.
