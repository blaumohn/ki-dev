# Tokenmessung, Aufgabenschnitt und Verbrauchsprognose

Stand: 2026-09-19. Materialisierung des Nutzerauftrags zur Verbrauchsmessung
und Mehrmodell-Einschätzung. Dieser Systementwurf ergänzt den normativen
[Orchestrator-Vertrag](../pending/design-notes.de.md#orchestrator).
Die Umsetzung wird in Beads unter **ki-dev-ablauf-wu0** geführt. Dieses
Dokument beschreibt das Zielbild; es behauptet keine implementierten
Estimatoren, bestandenen manuellen Tests oder nachgewiesene Einsparung.

## Normativer V1-Entwicklungsvertrag (2026-09-20)

Für den V1-Schnitt gilt jetzt der [normative Vertrag](v1-safety-contract.de.md)
mit [Typ-Stubs](v1/contracts.pyi) und [Tabellen/Offline-Prüffällen](v1/decisions.json).
Er ersetzt widersprechende Empfehlungen und noch als offen bezeichnete
Entwurfsfragen dieses Zielbilds. Die vier Entscheidungen stehen unter wu0.3.7;
kleine Implementierungsblätter und Betriebsnachweise unter wu0.10 sowie den
verknüpften wu0.3/.4.1-Aufträgen. Zahlenwerte bleiben bis zur evidenzbasierten
Profilfreigabe REQUIRED_NO_DEFAULT. Installationsabhängige Einschaltbelege
liegen in wu0.10.2.1/.2; jbr.4 bildet die abschließende Abnahme nach uar.

## Verbindlicher V1-Schnitt vor jbr (2026-09-19)

Der minimale Bau–Review-Loop **ki-dev-ablauf-jbr** benötigt vor dem Go-Live
das Schutzpaket **ki-dev-ablauf-wu0.10**. Der reale Lauf **uar.2** wartet
auf dessen konkrete Abnahme **wu0.10.4**. Nicht das gesamte wu0-Epic ist
Go-Live-Voraussetzung.

Anlass laut Nutzerbericht: Ein früher Lauf verbrauchte das Kontingent durch
ein Beads-Artefakt im Diff, technische Probleme, viele Iterationen und eine
zu große Aufgabe. Tokenverbrauch ist deshalb der **Herzschlag des Agenten**:
ein Betriebssignal, das zusammen mit Fortschritt und Ergebnis betrachtet wird.
Es ist weder ein Beweis fachlicher Leistung noch eine vollständige Sicht auf
das kontoweite Fünfstundenfenster.

### Ablauf und Grenzen

1. In der Materialisierung strukturierte Modellurteile für denselben
   eingefrorenen Auftrag und dasselbe Ausführungsprofil bereitstellen.
   V1 kann diese importieren; automatische Mehrmodell-Orchestrierung ist später.
2. Die austauschbare Strategie `max_upper_v1` nimmt die höchste begründete
   Schätzobergrenze. Verfahren, Version, Annahmen und Quellen werden gespeichert.
   Fehlende Urteile und widersprüchliche Annahmen bleiben sichtbar.
3. Ist diese Obergrenze **größer als die konfigurierte Auflösungsgrenze X**,
   startet der Vorgang nicht. Er wird außerhalb des Loops in sinnvoll
   abnehmbare Teilvorgänge zerlegt; jeder Teil wird neu geschätzt.
4. Eine ausdrücklich konfigurierte Regel leitet Aufgabenbudget und
   Aufrufbudget aus Schätzung, Reservefaktor und festen Kappen ab.
   Der einzelne Aufruf erhält höchstens das verfügbare Restbudget.
   Bereits verbuchter Schätzaufwand und späterer Review-/Reparaturaufwand
   werden gemäß festgelegter Budgetdefinition berücksichtigt.
5. Der Anbieteradapter misst während der eigenen laufenden, exklusiv
   gebundenen Sitzung. Bevorzugt: kumulativer Zähler minus persistierter
   Startbasis. Andernfalls: Summe belegbar eindeutiger Requests des Aufrufs.
   Keine vollständige historische Request-Rekonstruktion als V1-Pflicht.
6. Synchrone Kontroll-Hooks melden normalisierte Messungen. Die gemeinsame
   Budgetkontrolle veranlasst bei Überschreitung oder unzulässiger Messlücke
   den tatsächlichen Prozessabbruch über den Adapter/Prozessrunner.
   Bloßes Werkzeug-Deny oder Modellfeedback ist kein ausreichender Stopp.
   Ein äußerer Timeout wirkt auch ohne neue Werkzeugereignisse.
7. `ki-dev` speichert den bekannten Verbrauch und pausiert. Der Mensch
   untersucht z.B. Zugriffsschleifen, Binärdateien, unbegründet große Diffs
   oder Aufgabenumfang und entscheidet über Korrektur, Zerlegung und Resume.
   Keine automatische Ursachenanalyse oder automatische Wiederholung in V1.
8. Resume behält die Bilanz; fehlender Restverbrauch wird nicht null.
   Abschluss-JSON dient als Abgleich, nicht als zusätzlicher Summand.
   Eigene versionierte Mess-/Ergebnisartefakte bilden die spätere Lerngrundlage.

Beispielwerte sind keine Defaults: Obergrenzen 60.000/90.000 bei X=80.000
verlangen Aufteilung. 30.000/45.000 ergeben 45.000. Ein ausdrücklich gewählter
Reservefaktor 1,5 ergibt 67.500 Aufgabenbudget, sofern die feste Kappe genügt.
Nach 20.000 verbuchten Tokens bleiben 47.500. Bei Sitzungsgesamtstand 100.000
vor Start und 135.000 beim Hook beträgt der Aufrufverbrauch 35.000; erneutes
Lesen desselben Standes addiert nichts.

**Stoppschwelle, keine harte Tokenobergrenze:** Messverzögerung und der laufende
Modellrequest können eine Überschreitung verursachen. Zähleraktualität am Hook,
Zählerwechsel/Compaction und wirksamer Prozessabbruch einschließlich relevanter
Kindprozesse müssen für die eingesetzten CLI-Versionen belegt werden.
Fehlende Basis, Reset oder unklare Sitzungsbindung führen zur ausgewiesenen
Messlücke und Pause. Historische Fremdsitzungen, SQLite-Sammlungen und ein
allgemeiner Reader-Index sind keine Voraussetzung; vorhandene Reader werden
für die aktive eigene Sitzung wiederverwendet.

### Feste Modulgrenzen

- **Anbieterpaket:** CLI-Argumente, verifizierte Versionen und Schemafreigabe,
  JSON-/Transkriptparser, Token-Normalisierung, Hook-Ereignisse sowie
  CLI-spezifische Abbruchanbindung. Liefert explizite Anbieterfamilie,
  Messfähigkeit und Nachweisanforderungen vor Reservierung.
- **Gemeinsamer Vertrag:** normalisierte Messwerte, Quelle/Version, Messalter,
  Call-/Sitzungsbindung, Status und Stopgrund; keine Anbieter-Rohfelder.
- **Gemeinsame Kontrolle/Bilanz:** Budgetregel, atomare Reservierung,
  genau einmal zurechnen, Pause und Resume. Keine Adapternamens-Sonderfälle,
  CLI-Versionslisten oder Hook-Parser. Anbieterneutrale Prozessmechanik darf
  gemeinsam bleiben; keine zweite Safety-Bilanz.
- **Schätzzusammenführung:** kleine austauschbare Strategie-Schnittstelle.
  V1 `max_upper_v1`; ein späteres Bayes-Verfahren kann zusätzlich versionierte
  Kalibrierungsdaten verwenden. Ergebnisvertrag bleibt für Loop und Adapter
  gleich. Kein großes Plugin-System erforderlich.

Konkrete Module, Symbole, Datenfelder, Import-Richtung, Migrationsfolge,
Hook-Transport, Stopfristen, Pflichtfelder und Budgetsemantik werden vor der
Umsetzung in **wu0.3.7** festgelegt. Diese Materialisierung ersetzt den
technischen Entwurfsnachweis nicht.

### Kleine Umsetzungsaufträge und Go-Live-Abnahme

| Auftrag | Begrenztes Ergebnis |
| --- | --- |
| wu0.3.7 | Entwurf/Review: implementierbare Verträge und Beispiele vorgeben |
| wu0.3.2, .3.8, .3.3 | Aufrufbilanz, echte Aufgabenbindung, Aufwandsarten |
| wu0.4.1.1 | Schätzdatentypen und austauschbare max-Strategie |
| wu0.4.1.2 | Schätzartefakt, X-Prüfung und Budgetregel im Startpfad |
| wu0.10.1.1 | Eigene CLI-Prozesse gezielt und begrenzt abbrechen |
| wu0.10.1.2 | Normalisierte Live-Werte gegen Restbudgets prüfen |
| wu0.10.2 | Ausschließlich eigene Kontroll-Hooks im Container freigeben |
| wu0.3.6.1 / .3.6.2 | Claude-/Codex-Paket nach festem Vertrag anbinden |
| wu0.3.4 / .3.1 / .3.5 | Restart, Offline-Gesamtlauf, reproduzierbare Provenienz |
| wu0.3.6.3 / .1 | Reale Mess-/Abbruchbelege und separater Kontingentabgleich |
| wu0.10.3 | Bestehende Betriebs-/Nachweiskonflikte ausdrücklich entscheiden |
| wu0.10.4 | Pflichtnachweise zusammenführen; blockiert uar.2 |

Jeder Umsetzungsauftrag nennt Einstiegssymbole, Nicht-Umfang, kleine
Input/Output-Beispiele und gezielte Prüfungen. Er ist für ein kleineres
Umsetzermodell zugeschnitten. Fehlende Architekturentscheidungen werden als
Blocker gemeldet, nicht vom Umsetzer erfunden. Elternaufträge sind
Abnahmeklammern und kein Auftrag zur pauschalen Gesamtimplementierung.

Offene konkrete Voraussetzungen bleiben sichtbar:
Die aktuelle Containerpolicy deaktiviert beide Hook-Systeme. Sie muss nur
die kontrollierten ki-dev-Hooks zulassen und fremde Quellen weiterhin
ausschließen. Claude besitzt im aktuellen Adapter keinen verifizierten
Kontingentmessweg; die bestehende Sperre wird nicht still abgeschaltet.
**wu0.10.3** klärt außerdem den Widerspruch zwischen echtem uar-Nachweis und
der weiterhin gültigen Testregel **him**. Vorhandene echte Belege zuerst
prüfen; diese Materialisierung autorisiert keine Modellläufe oder
umbenannten produktiven Smoke-Ausnahmen.

### Autonome Grenze und interaktive Übergabe

Diese Regel gilt bereits für die Agenten, die V1 implementieren. Die spätere
technische Durchsetzung durch ki-dev ist zusätzlich erforderlich.

| Situation | Agent darf selbst | Stopppunkt / interaktive Übergabe |
| --- | --- | --- |
| Eigene Hook-Konfiguration ist planmäßig deaktiviert | Die beauftragten Repo-/Launcheränderungen nach dem freigegebenen Vertrag umsetzen und lokal prüfen | Externe Policy, fehlende Rechte, fehlender Mount oder notwendige interaktive Registrierung verhindert dies |
| CLI-/Hook-Verhalten weicht vom Vertrag ab | Effektive Version und Konfigurationsquelle gezielt prüfen | Version/Fähigkeit bleibt ungeklärt; kein Upgrade, Quellwechsel oder neuer Parser auf Verdacht |
| Zugriff oder Anmeldung fehlt | Begrenzten Befund und benötigte Aktion feststellen | Bei bestätigter externer Sperre keine alternativen Zugriffswege probieren |
| Eigener Code oder lokaler Test ist fehlerhaft | Konkrete Codekorrektur innerhalb Auftrag und Budget | Gleicher Fehler ohne neue Evidenz; Ursache verlangt äußere Änderung oder neue Architekturentscheidung |
| Tokenquelle fehlt/veraltet oder Abbruch wirkt nicht | Vorliegende Metadaten und lokalen Prozessbefund sichern | Kein geschützter Lauf starten/fortsetzen; Adapterfähigkeit ungeklärt |
| Budget erreicht oder externe Wirkung unklar | Bekannten Verbrauch und Arbeitsstand sichern | Pausieren; kein automatischer Retry, keine Budgetanhebung |
| Echter Nachweis erfordert verbotenen Modelltest | Vorhandene geeignete Belege prüfen | Entscheidung in wu0.10.3 einholen; kein umbenannter Smoke-Lauf |

Bei unklarer Ursache ist höchstens eine gezielte lokale Diagnosefolge erlaubt:
effektive Version/Konfiguration, begrenzter Fehlerbefund, Vergleich mit dem
freigegebenen Vertrag. Ihre Zeit- und Versuchsgrenze muss vorher feststehen;
**wu0.3.7** gibt konkrete Werte vor. Ohne diese Grenze keine offene autonome
Umgebungsdiagnose. Unveränderte Wiederholungen oder eine Kette alternativer
Zugriffswege sind keine neue Diagnose. Bestätigte externe Sperre oder fehlende
Befugnis erfordert sofortige Pause des betroffenen Arbeitszweigs.
Unabhängige unbetroffene Arbeit darf weitergehen; die blockierte Abnahme bleibt offen.

Eine Übergabe enthält: Vorgang/Call, Soll/Ist, effektive CLI-/Konfigurationsversion,
bereits ausgeführte gezielte Prüfung, bekannten Verbrauch und Messlücken,
benötigte Benutzeraktion/Entscheidung sowie genaue Wiederaufnahmebedingung.
Nur bereinigte Metadaten; keine Rohtranskripte oder Secrets.
Nach bestätigter Änderung/Freigabe gezielt fortsetzen, niemals die Bilanz löschen.

Die Einschaltanleitung für jeden Adapter muss vor mechanischer Umsetzung
Konfigurationsquelle und Präzedenz, Hook-Datei, eventuell nötige Trust-/Registrierung,
Rechte/Mounts, modellfreie Wirksamkeitsprüfung und Rückbau benennen.
Das steht noch als Entwurfsnachweis in **wu0.3.7** aus; **wu0.10.2** setzt es um.
Es ist keine pauschale Erlaubnis, fremde Hooks oder globale Schutzregeln zu ändern.

Arbeitsanweisungen allein garantieren kein Ende eines laufenden Agenten.
Prozessabbruch/Timeout und Startprüfungen aus **wu0.10.1/.2** bleiben
Go-Live-Voraussetzung. Bis dahin wird unbeaufsichtigter Verbrauchsschutz nicht behauptet.

### Nachgelagerte Verbesserungen

Der restliche automatische Mehrmodell-Ausbau **wu0.4**, die Kalibrierung
**wu0.5/.6**, gelernte Guard-Prognosen **wu0.7** und Wirkungsauswertung **wu0.8**
blockieren jbr nicht. Die explizite V1-Budgetregel braucht keine bereits
kalibrierte Schätzung; sie ist eine konservative Betriebseinstellung und
keine statistisch bestätigte Garantie.

**wu0.11** untersucht nach jbr einen Bayes-Estimator gegen die max-Baseline.
**urq.8** untersucht nach dem bestehenden urq-Pilot NL-Objekt-Ähnlichkeit,
Embedding-Kandidaten und vorab zu definierende Vergleichsdichte.
Die eingefrorenen urq-Pilotkriterien werden dadurch nicht nachträglich verändert.

Beide Themen können Fallstudien liefern: reproduzierbare
Methodik, Baselinevergleich, eigene Messwerte, Beispiele und klare Grenzen.
Erfolg, Einsparung oder Überlegenheit werden erst nach tatsächlichen Ergebnissen
behauptet; auch ein sauber belegtes negatives Ergebnis ist ein Forschungsbefund.
Keine bezahlten Modell-/Embedding-Berechnungen aus dieser Materialisierung ableiten.

## Zweck und bestehende Grundlage

Tokenverbrauch ist ein Betriebssignal des Orchestrators. Zusammen mit
fachlichem Fortschritt und Ergebnisqualität macht er teure Reparaturschleifen,
übermäßigen Kontextaufbau und ungünstige Aufgabenverteilung sichtbar. Hoher
Verbrauch allein beweist keinen Fehler; niedriger Verbrauch bei unvollständiger
Umsetzung ist kein Erfolg.

Die ohnehin nötige Einschätzung bei der Materialisierung von Beads-Vorgängen
wird für mehrere unabhängige Modellurteile genutzt. Ihr erster Zweck ist ein
guter Aufgabenschnitt: vollständig überprüfbare Ergebnisse, beherrschbare
Unsicherheit und sinnvoll geteilter Kontext. Zu große Aufgaben riskieren
Teilumsetzung und Nacharbeit; zu kleine Aufgaben wiederholen Kontextaufnahme,
Schätzung und Übergaben. Die Verbrauchsprognose entsteht aus derselben Arbeit
und wird anschließend gegen wirklichen Verbrauch kalibriert.

Vorhanden sind bereits:

- `src/ki_dev/adapter/executors/metering.py`: strukturierte CLI-Verbrauchsergebnisse,
  Claude-Kontextmessung und lokale Codex-Kontingentmessung.
- `scripts/analyze_claude_usage.py`: deterministische Auswertung eines
  vorhandenen Claude-Laufs, einschließlich Deduplizierung von Modellantworten.
- `CallLedger` und `QuotaBaseline` in `src/ki_dev/runner/safety.py`: persistierte
  Laufbilanz, Aufrufreservierungen und Kontingentbasislinien.
- Guards in `src/ki_dev/runner/runtime.py`: technische Freigabe/Pause, getrennte
  Aufgabenbudgets und Kontingentreserve sowie Kontextprüfung.

Diese Grundlagen werden erweitert. Der vorhandene Analyseskript ist eine
Ausgangsbasis, noch kein allgemeiner versionssicherer Messvertrag. Die heutigen
Grenzen sind in [loop-runtime.de.md](../loop-runtime.de.md) beschrieben;
insbesondere ersetzt eine neue Prognose keinen fehlenden Kontingentnachweis.

## Systemskizze und Modulgrenzen

```mermaid
flowchart TD
    R["CLI-Ereignisse / lokale Sitzungsdateien"] --> M["Tokenmessung: deterministische Metadatenextraktion"]
    M --> B["Verbrauchsbilanz: Auftrag, Aufruf, Sitzung und Rolle"]
    P["Versionierter Aufgabenstand und Ausführungsprofil"] --> E["Estimatoren: unabhängige Modellurteile"]
    E --> S["Materialisierung: begründeter Aufgabenschnitt in Beads"]
    E --> A["Unveränderliche Schätzartefakte"]
    B --> K["Kalibrierung: Prognose gegen Ist-Verbrauch und Ergebnis"]
    A --> K
    Q["Geprüfte Abnahmen, Teilumsetzung und Nacharbeit"] --> K
    K --> E
    K --> G["Vorhandene Orchestrierungs-Guards"]
    B --> G
    M -->|"Kontingentwert separat"| G
    G --> N["Nächsten Schritt zulassen oder pausieren"]
```

Die Bezeichnungen sind fachliche Modulgrenzen. Neue Python-Dateinamen sind
Vorschläge; ihr Zuschnitt folgt den vorhandenen Verträgen und der tatsächlichen
Komplexität. Es entstehen kein zusätzlicher Dienst und keine zweite Safety-Bilanz.

| Modul | Verantwortung und Grenze | Anschluss im Repository |
| --- | --- | --- |
| Tokenmessung / Anbieterpakete | CLI-Versionen, Quellenparser, Normalisierung, Hooks und Stop-Anbindung je Anbieter; keine eigene Budgetregel | Bestehende `adapter/executors/metering.py`-/`usage.py`-Reader gezielt in Anbieterpakete verlagern; gemeinsame Datentypen anbieterneutral |
| Verbrauchsbilanz | Ereignisse genau einmal einem Auftrag/Aufruf zurechnen, Gesamtsummen abgleichen, Sitzungswechsel und Teilaufgaben zusammenführen | `CallLedger`/`RunStore` erweitern |
| Estimatoren | Aufgabengröße, Unsicherheit, Kontextbedarf, Schnittvorschläge und Verbrauchsintervalle beurteilen | vorgeschlagenes `estimation.py`; bestehende Executor-Verträge und Materialisierung nutzen |
| Kalibrierung | Schätzfehler und Token-Kontingent-Beziehung getrennt lernen, Modellstände und Gültigkeit versionieren | vorgeschlagenes `calibration.py`; rein datenbasierte Auswertung ohne Modellpflicht |
| Budgetsteuerung | Prognose und Messung gegen wirksame Grenzen prüfen, Reservierungen koordinieren, Pause/Handoff begründen | vorhandene `runner/safety.py`/`runner/runtime.py` |

Beads bleibt die Wahrheit für Aufgaben, Abhängigkeiten und Zustand. Messreihen,
Schätzungen und Kalibrierungsstände sind strukturierte versionierte Artefakte
mit Referenz aus Beads. Das Beads-Feld `estimate` bezeichnet Minuten und wird
nicht für Tokens oder eine fachliche Größenskala umgedeutet.

## Messvertrag und sparsame Extraktion

**Entwicklungsregel: Roh-Sitzungsdateien niemals vollständig in den
Agentenkontext laden.** Ein deterministischer Parser darf Dateien vollständig
durchlaufen, gibt aber ausschließlich gezielt freigegebene JSON-Metadaten aus.
Das gilt auch für Diagnose, Fehlermeldungen und Fixture-Erzeugung. Keine
Gesprächsinhalte, Prompts, Werkzeugausgaben, Zugangsdaten oder unbeschränkten
Ereignis-Dumps ausgeben. Eine Ausgabegrenze muss ihre Kürzung erkennbar machen.

Die Messung benötigt, soweit die Quelle sie tatsächlich bereitstellt:

| Daten | Bedeutung |
| --- | --- |
| Schema-/Parser-/CLI-Version und Quellenreferenz | Reproduzierbare Interpretation; unbekannte Version ist kein implizit gültiger Messwert |
| Provider, Konto-/Kontingentbezug und tatsächlich verwendetes Modell | Zusammenpassende Messungen identifizieren; angefordertes Modell getrennt vom bestätigten Modell halten; keine Credentials speichern |
| Bead-ID und Auftragsrevision, Lauf-, Aufruf-, Request-, Sitzungs- und Rollenkennung | Verbrauch zurechnen; fehlende Bindung ausdrücklich kennzeichnen |
| Ereigniszeit, Beobachtungszeit und Zählerbereich | Messalter, kumulative Zähler und einzelne Requests unterscheiden |
| Input, Cache-Lesen/-Schreiben, Output und verfügbare Unterkategorien | Providersemantik erhalten; enthaltenes Reasoning oder Cache nicht nochmals addieren |
| Messstatus und Vollständigkeit | Gemessen, teilweise vorhanden, nicht verfügbar oder nicht unterstützt unterscheiden; unbekannt ist nicht null |
| Kontingent-ID, Fensterdauer, Reset und verbrauchte Prozentpunkte | Separater kontoweiter Messwert, keine automatisch aufgabengenaue Tokenbuchung |

Aus Rohzählern entsteht ein normalisierter Verbrauch, bei dem jede Tokenmenge
genau einmal enthalten ist. Eine nicht vorhandene Kategorie ist nur dann null,
wenn der verifizierte Quellvertrag dies rechtfertigt. Kontextbelegung eines
Requests, kumulierte Eingabetokens über viele Requests und Kontingentprozent
sind unterschiedliche Messgrößen. Die physische Tokenzahl ist keine universelle
Kosten- oder Kontingenteinheit.

Streaming-Duplikate werden anhand geeigneter Request-/Antwortidentitäten
zusammengeführt. Kumulative Snapshots werden nicht summiert, sondern innerhalb
ihres belegten Zählerbereichs differenziert. Negative Differenzen, Compaction,
Sitzungsfortsetzung und Zählerwechsel verlangen eine explizite Behandlung;
unbekannte Vorgeschichte darf nicht zu null werden. CLI-Gesamtsummen und darin
enthaltene Einzelrequests dienen dem Abgleich, nicht einer doppelten Buchung.
Bei Abbruch bleiben bekannter Verbrauch und offene Restwirkung erhalten.

Ein unvollständiger letzter JSONL-Eintrag wird nach weiterem Schreiben erneut
gelesen. Fehler im Inneren einer Datei und Lücken bleiben sichtbar. Ein
inkrementeller Index darf später den Scan beschleunigen, muss aber Rotation,
Trunkierung, Kopien, mehrfach vorhandene Ereignisse und Neustart beherrschen.
Dateiänderungszeit und Zeilenreihenfolge garantieren keine Ereignisreihenfolge.
Die bestehende Suche nach dem neuesten Kontingentereignis wird nicht durch
eine unbelegte Dateiauswahl verkürzt.

## Manueller Messabgleich vor dem nächsten Loop

Der manuelle Smoke-Nachweis **ki-dev-ablauf-wu0.1** ist eine zusätzliche
Voraussetzung für **ki-dev-ablauf-uar.2**. Der vollständige Estimator-Ausbau ist
keine Voraussetzung für diesen Nachweis. Die Testregel aus
**ki-dev-ablauf-him** bleibt maßgeblich: Softwaretests starten keine echten
Modellanfragen; die dort verschobene technische Sperre hebt diese Regel nicht auf.

1. Konto/Kontingent, CLI-Version, Messdefinition, Fenster, Zeitpunkte und
   Vergleichstoleranz vorab festhalten. „Verbleibend“ aus `/status` und
   „verbraucht“ aus der Messquelle auf dieselbe Darstellung bringen.
2. Benutzerwert aus `/status` und kompakten `ki-dev`-Messwert möglichst zeitnah
   paaren; Messquelle und Alter mit ausgeben.
3. Vorher/Nachher-Werte aus ohnehin stattfindender Benutzerarbeit oder bereits
   vorhandenen passenden Belegen vergleichen. Keine zusätzlichen Modellläufe
   zum Erzeugen von Testverbrauch. Ohne solche Belege bleibt der Nachweis offen.
4. Wiederholtes Auslesen darf keinen Modellaufruf auslösen. Tokenzähler getrennt
   gegen bekannte strukturierte Ereignisse prüfen; Prozentübereinstimmung
   beweist noch keine exakte Tokenzählung.
5. Rundung, verzögerte Aktualisierung, Reset und fremde Kontonutzung dokumentieren.
   Für die spätere Verhältnis-Kalibrierung ungeeignete Intervalle ausschließen.

Der Nachweis gilt nur für die geprüfte Quelle und Konfiguration. Ein erfolgreicher
Codex-Abgleich behebt keine fehlende Claude-Kontingentquelle. Fehlende/veraltete
Messwerte geben keinen Lauf frei. Es werden keine bestandenen Tests vorweggenommen.

## Einschätzung als Teil der Materialisierung

Jeder Schätzer erhält denselben eingefrorenen Aufgabenstand: Ziel, begrenzten
relevanten Kontext, Abnahmekriterien, Abhängigkeiten und vorgesehenes
Ausführungsprofil. Zunächst sind zwei unterschiedliche Modelle als Vergleich
vorgesehen; Modellzahl, Eingabeumfang, Aufrufzahl und Budget sind begrenzt.
Die Modelle sehen die anderen Einschätzungen erst nach ihrer eigenen Abgabe.
Verschiedene Modelle sind deshalb noch nicht statistisch unabhängige Schätzer.

Eine Schätzung enthält getrennt:

- Umfang auf einer versionierten Skala mit Referenzaufgaben;
- Unklarheiten, Kontextbedarf und Vollständigkeitsrisiken;
- begründetes Schnitturteil mit prüfbaren Ergebnissen und Übergaben;
- erwarteten Tokenverbrauch und vorsichtige Obergrenze samt Annahmen zu
  Implementierung, Tests, Review und Reparatur;
- Schätzer-/Promptversion, tatsächliches Schätzmodell und Zielprofil der
  Ausführung, einschließlich Modell, Effort und Arbeitsablauf, soweit bekannt.

Die Ergebnisse verbessern dieselbe Materialisierung; es arbeiten nicht mehrere
Materialisierer konkurrierend schreibend am Beads-Graphen. Unterschiedliche
Urteile werden anhand ihrer Annahmen ausgewertet. Ein bloßer Mittelwert kann
einen wichtigen Hinweis auf fehlende Klärung verdecken. Fachliche Entscheidungen
und Auftragsänderungen bleiben im bestehenden Planungs-/Freigabevertrag.

Der Aufwand der Schätzer wird einschließlich Kontextaufnahme verbucht. Die
Schätzung wird vor der Ausführung gespeichert. Ein neuer Auftragsstand oder
Zuschnitt erhält neue Prognosen; die alten bleiben für den späteren Vergleich
erhalten. Familienbezug und ursprünglicher Gesamtumfang verbinden Eltern- und
Teilaufgaben. Gemeinsamer Planungsaufwand wird genau einmal zugerechnet.

## Kalibrierung und Bewertung

Zwei verschiedene Beziehungen werden gelernt: **Aufgabe → erwarteter
Verbrauch** und **Tokenverbrauch → Kontingentänderung**. Eine brauchbare
Tokenprognose setzt keine stabile Kontingentumrechnung voraus.

Für ein geeignetes Intervall ohne Reset und unbekannten Parallelverbrauch ist
`100 × ΔTokens / ΔProzentpunkte` ein Kandidat für die effektive Kapazität des
beobachteten Profils. 40.000 Tokens bei 2 Prozentpunkten ergeben rechnerisch
2 Millionen Tokens für 100 Prozent. Das ist eine empirische Hochrechnung,
keine feste Anbieterzusage. Kleine Prozentdifferenzen, Rundung und zeitlich
versetzte Messwerte können das Ergebnis stark verzerren.

Provider, Kontingent, Modellprofil und Tokenmix werden getrennt betrachtet.
Cache-/Output-Anteile und Betriebsänderungen können das Verhältnis verschieben.
Ungewichtete Tokens, empirisch gewichtete Kategorien und eine direkte Prognose
der Prozentpunkte sind zu vergleichen. Messfenster und Kontingent-ID dürfen
nicht allein aus einem Feldnamen wie „primary“ abgeleitet werden. Drift oder
instabile Verhältnisse führen zu ungültiger Prognose, nicht zu erfundener Präzision.

Für die Aufgabengröße wird der **Gesamtverbrauch gegenüber dem vorher
geschätzten, vollständig erledigten Umfang** ausgewertet. Ein Quotient setzt
eine sinnvoll teilbare, stabile Größeneinheit voraus. Bei ordinalen Klassen
wie S/M/L wird stattdessen innerhalb der Klassen verglichen. Bei einer
Aufteilung bleibt der eingefrorene Elternumfang der Vergleichsbezug; neu
summierte Kindschätzungen dürfen den Nenner nicht künstlich vergrößern.

Gesamtverbrauch umfasst Schätzung, Umsetzung, wiederholtes Kontextlesen,
Übergaben, Review, Fehlversuche und Nacharbeit. Teilumsetzungen/Abbrüche bleiben
mit Aufwand und unerfüllten Abnahmen sichtbar. Ergebnisqualität und Nacharbeit
werden neben Tokens berichtet. Ein günstiger Quotient allein ist kein Erfolg.
Die erwartete ungünstige Wirkung sowohl sehr kleiner als auch sehr großer
Schnitte ist eine Hypothese, kein schon nachgewiesenes universelles Optimum.

Begonnen wird mit historischen Vergleichsaufgaben und Korrekturfaktoren je
Schätzer/Aufgabentyp. Gewichtete Kombination oder Regression kommen erst bei
ausreichenden Daten hinzu. Ein vom Modell genanntes „P90“ ist ohne empirische
Abdeckung nur eine Behauptung; bis zur Kalibrierung heißt es Schätzobergrenze.
Fehler, deutliche Unterschätzungen, Überschreitungen der Obergrenze und deren
Breite werden auf zeitlich späteren Aufgaben ausgewertet. Auftragsfamilien
werden nicht zwischen Anpassungs- und Validierungsdaten verteilt. Mindestdaten,
Fehlergrenzen und Aktivierungskriterien werden vor der Bewertung festgelegt.
Wenig Daten, wechselnde Aufgabenmischung und Auswahlverzerrung begrenzen Aussagen.

## Vorausschauende Budgetsteuerung

Dieser Abschnitt beschreibt den nachgelagerten kalibrierten Ausbau. Gelernte
Prognosen werden zunächst nur protokolliert und gegen tatsächliche Ergebnisse
geprüft. Erst nach belegter Güte dürfen sie automatische Freigaben beeinflussen.
Die oben beschriebene explizite V1-Budgetregel mit max-Strategie und Kappen
gilt bereits vor jbr; sie beansprucht keine kalibrierte Prognosegüte.
Für jede Budgetdimension getrennt gilt:

```text
konservative Prognose des nächsten Schritts
+ noch nicht verbuchter reservierter Restverbrauch anderer Arbeit
+ Sicherheitsreserve
<= verfügbares Budget dieser Dimension
```

Tokens werden nur mit Tokens verglichen; eine Prozentprüfung braucht eine gültige
Umrechnung oder direkt kalibrierte Kontingentprognose. Kontingente verschiedener
Konten werden nicht addiert. Bereits im gemessenen Verbrauch enthaltene Mengen
dürfen nicht nochmals als Reservierung abgezogen werden. Eine kontoweite
Reservierung ist nur bei gemeinsamem, atomarem Speicher aller beteiligten
Orchestratoren belastbar; fremde Sitzungen und andere Geräte bleiben sonst eine
Unsicherheit. Nach jedem Schritt werden Ist-Verbrauch und Restaufwand abgeglichen.

Resume, neue Sitzung oder Modellwechsel setzen keine Bilanz zurück. Veraltete
Prognosen, geänderte Aufgaben und Drift benötigen eine explizite konservative
Behandlung. Vorhandene Token-/Kontingent-/Kontextgrenzen bleiben zusätzlich
wirksam. Eine Schätzung gestattet einem Agenten weder Budgetanhebung noch
Selbstfreigabe. Pausen benennen Ursache und Belege und verwenden den bestehenden
Handoff-Vertrag. Die Vorprüfung garantiert keine harte Echtzeitobergrenze für
einen bereits laufenden, nicht entsprechend begrenzbaren Aufruf.

## Alternativen und Bewertung

| Frage | Alternative | Bewertung / bevorzugter Einstieg |
| --- | --- | --- |
| Datenquelle | Strukturierte CLI-Ergebnisse plus gezielte lokale JSON-Extraktion | Baut auf vorhandenen Adaptern auf, modellverbrauchsfrei; Rohformate und Aktualität müssen geprüft werden. Einstieg. |
| Datenquelle | Direkte strukturierte Status-/Ereignisschnittstelle, etwa Codex App Server | Kandidat für frischere Daten und weniger Dateiformatkopplung; Verfügbarkeit, Authentifizierung und Vertrag gegen die eingesetzte CLI prüfen. Keine Voraussetzung für den ersten Abgleich. |
| Datenquelle | Agent liest vollständige Sitzungen oder schätzt Tokens aus Textlänge | Verursacht selbst Kontextkosten bzw. liefert keine exakten Verbrauchswerte. Für Messung verworfen. |
| Modulaufbau | Kleine lokale Fachmodule mit vorhandener Bilanz und Guards | Klare Zuständigkeiten ohne neuen Dienst; bevorzugt. Anbieterpakete sind die verbindliche Änderungsgrenze; gemeinsame Verträge bleiben neutral. |
| Modulaufbau | Alles im Runtime-Guard oder eigener Telemetriedienst | Ersteres vermischt Parsing/Prognose/Entscheidung; letzteres erhöht Betrieb und Synchronisationsaufwand. Derzeit nicht erforderlich. |
| Schätzung | Ein vorhandenes Modell und historische Vergleichswerte | Günstige Vergleichsbasis; entdeckt weniger unterschiedliche Annahmen. Als Baseline erhalten. |
| Schätzung | Zwei unabhängige Modellurteile auf demselben Eingang | Bevorzugter Einstieg für die Schnittprüfung; Mehrkosten zählen mit, korrelierte Fehler bleiben möglich. |
| Schätzung | Viele Modelle für jede Kleinigkeit | Höhere Kosten und Latenz ohne garantierten Erkenntnisgewinn. Erst bei belegtem Zusatznutzen erweitern. |
| Lernen | Vergleichsaufgaben, Korrekturfaktoren, später einfache Regression/Gewichtung | Nachvollziehbar, offline auswertbar, geringer Datenbedarf gegenüber Fine-Tuning. Bevorzugter Start. |
| Lernen | Eigenes Sprachmodell-Fine-Tuning | Benötigt genügend saubere Daten und zusätzliche Pflege. Erst bei nachgewiesenem Vorteil gegenüber der Baseline ein eigener Entscheid. |
| Schutz | Feste Grenzen plus kalibrierte Prognose | Beibehaltung vorhandener Schutzwirkung und frühere Pause bei ungünstiger Erwartung. Zielbild. |
| Schutz | Ausschließlich Schätzerurteil | Kann systematisch unterschätzen und schützt nicht vor ungemessenem Verbrauch. Verworfen. |

## Herausforderungen und Prüfnachweise

| Hauptproblem | Erforderlicher Nachweis |
| --- | --- |
| Provider unterscheiden Tokenkategorien und Zählerbereiche | Kleine Fixtures mit bekannten Summen, Cache-/Reasoning-Untergruppen, Duplikaten und Zählerwechseln |
| Sitzungsdaten wachsen während des Lesens | Teilzeilen, Rotation, Trunkierung, Neustart und wiederholtes Lesen verlieren/verdoppeln keinen bekannten Verbrauch |
| Messung kann selbst Agentenkontext verschwenden | Sentinel-Inhalte erscheinen weder in Ausgabe noch Fehlerdiagnose; Ausgabe und persistierte Projektion sind begrenzt |
| Kontoweite Quota ist nicht aufgabengenaue Buchhaltung | Konto-/Fensterbindung, Messalter, Parallelverbrauch und Grenzen der Attribution ausdrücklich geprüft |
| Teilaufgaben/Resume können die Bilanz verfälschen | Bekannter Gesamtverbrauch über Eltern, Kinder, Sitzungswechsel und abgebrochene Versuche bleibt erhalten |
| Mehrere Modelle können gemeinsam falsch liegen | Vorab gespeicherte Prognosen gegen spätere Ergebnisse, Baselinevergleich und getrennte Unterschätzungsanalyse |
| Niedrige Tokens können schlechte Ergebnisse verdecken | Vollständigkeit, Regressionen und Nacharbeit neben Verbrauch ausweisen; Abbrüche nicht aus der Stichprobe entfernen |
| Gleichzeitige Freigaben können Restbudget mehrfach vergeben | Atomare Reservierung/Abgleich mit lokalen Stubs; unbekannte externe Aktivität als Grenze benennen |

Die offenen Umsetzungsschritte, ihr Zustand und ihre Abhängigkeiten stehen
ausschließlich im Beads-Epic **ki-dev-ablauf-wu0**. Der manuelle Abgleich und
die automatisierten Offline-Nachweise bleiben unterscheidbar. Die Wirkung auf
die Güte von `ki-dev` wird gemessen; dieser Entwurf behauptet sie noch nicht.
