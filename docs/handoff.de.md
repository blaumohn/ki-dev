# Manuelle Arbeitsübergaben mit `ki-dev handoff`

`handoff` ist ein experimentelles Übergangswerkzeug: intern scherzhaft
„mensch-dev loop“. Es soll kurzfristig helfen, Aufträge, Abläufe und Prompts
von Hand effizient zu erproben, bis `ki-dev loop` betrieblich nutzbar ist.
Der Nutzen liegt in kurzen Übergaben und weniger Handarbeit. Auch
ausführungsreife Aufträge bleiben auf einen kleinen Umsetzungsschnitt
begrenzt: notwendige Anforderungen, Schnittstellen und Prüfnachweise; bei
fachlicher Übergröße teilen statt immer mehr Details anzuhäufen.

Die Zuordnung von Auftrag, Arbeitsstand und Prüfbericht verantwortest du als
Mensch. `handoff` garantiert keine Bindung an den Quellstand. Halte den
Arbeitsstand während Vorlauf und Review passend; nach weiteren Änderungen
starte den Vorlauf erneut.

`ki-dev handoff BEAD_ID --step STEP` prüft einen Bead formal und gibt eine
kurze, kopierbare Arbeitsübergabe aus. Du startest die passende Agentensitzung
selbst und fügst den Text dort ein. Diese Form liest den Bead nur
(`bd --readonly show BEAD_ID --json` im aktuellen Arbeitsverzeichnis, Frist
10 s) und startet keinen Agenten. Für `--step review` gilt eine ausdrückliche
Ausnahme vom sonst rein lesenden Vertrag: siehe
[Deterministischer Vorlauf vor der Review-Übergabe](#deterministischer-vorlauf-vor-der-review-übergabe-step-review).
Eine zweite Form, die eine Codex-Sitzung als Quelle erschließt und dabei
schreibt, steht [weiter unten](#codex-sitzung-als-quelle-handoff-map).

## Die fünf Aufrufe

`--step` ist erforderlich; es gibt keine automatische Auswahl.

```bash
ki-dev handoff projekt-42 --step map          # Rohnotizen kartieren
ki-dev handoff projekt-42 --step graph        # dünne Vorgänge anlegen
ki-dev handoff projekt-42 --step materialize  # einen Vorgang ausführungsreif machen
ki-dev handoff projekt-42 --step build        # materialisierten Bead umsetzen
ki-dev handoff projekt-42 --step review       # getrennt reviewen
```

Die Ausgabe ist unfarbiger Klartext ohne Zeilenumbruch nach Terminalbreite. Sie
lässt sich umleiten (`ki-dev handoff … > uebergabe.txt`) oder aus dem Terminal
kopieren. `ki-dev handoff --help` fasst das auf Deutsch zusammen.

## Freie lokale Sitzung (`handoff local`)

```bash
ki-dev handoff local > uebergabe.txt
```

Für Sitzungen ohne Auftrag aus Beads. Der Aufruf braucht weder Bead noch
Datenbankverbindung noch `bd` im PATH, hat keine `--step`-Pflicht und schreibt
nichts. Mit `--step`, `--review-of`, `--check-args`, `--next-turn`,
`--feedback-file`, `--agent` oder `--session` kombiniert endet er mit Exit 2.
Die Ausgabe besteht aus einer festen kurzen Basis (`Schritt: local`) und dem
gesonderten Leitlinienblock mit den allgemeinen Abschnitten (`common`) aller
Regelquellen (siehe [Mitgelieferte Leitlinien](#mitgelieferte-leitlinien));
die phasenspezifischen Abschnitte gehören nicht dazu. Die Basisgrenze
(`base_max_chars`) gilt nur für die Basis; Leitlinienquelle fehlt: Exit 1,
ungültig: Exit 2.

Es ist keine Planungsrolle gewählt: Die Übergabe nennt nur Lesebefehle
(`bd show/ready/prime`) und keine Aufforderung zu `--claim` oder `close`. Eine
ausdrücklich wählbare Planungsrolle gibt es nicht; wer Beads-Status ändern
soll, sagt das in der Sitzung selbst.

## Pflichtfelder je Schritt

### Geerbte Epic-Hinweise

Ein Epic-Hinweis vermittelt Ziel, Zusammenhang und begründende Entscheidungen
des Elternvorhabens. Er hilft dem Agenten, die Aufgabe eines untergeordneten
Vorgangs im Ganzen zu verstehen und eine dazu passende Lösung zu entwickeln.
Die Übergabe fordert dazu auf, diesen Kontext zu berücksichtigen und
Widersprüche zum konkreten Auftrag zu melden.

Beispiel für den Kontext eines Epics:

> Wir erproben manuelle Agentenübergaben, bevor wir den Ablauf automatisieren.
> Der Mensch startet die Sitzungen und entscheidet über weitere Schritte.

Ein Kind-Vorgang zur Vorbereitung einer Übergabe kann daraus verstehen,
warum ein automatischer Agentenstart am Ziel des Epics vorbeigehen würde.
Der Hinweis darf auch geltende Einschränkungen enthalten; sein Zweck reicht
über eine Sammlung von Handlungsregeln hinaus.

Untergeordnete Vorgänge erben automatisch `metadata.handoff.epic_context`
aus ihren Epic-Vorfahren über Beads-Beziehungen vom Typ `parent-child`.
Auch Zwischenvorgänge ohne eigenen Hinweis unterbrechen die Vererbung nicht.
Die Ausgabe nennt die Epic-ID und zeigt Hinweise vom äußersten zum nächsten
Epic; sie werden nicht überschrieben. Blockierungs- und Herkunftsbeziehungen
liefern keinen Kontext. Widersprüche klärt der Mensch.

Das Feld `epic_context` enthält diesen Epic-Kontext. Es gibt
kein zusätzliches Pflichtfeld und keine automatische Bewertung, ob ein Text
das Epic inhaltlich ausreichend erklärt.

Das optionale Feld enthält einen nichtleeren Text mit höchstens 600 Zeichen.
Fehlerhafte Hinweise, nicht lesbare Eltern, mehrdeutige Eltern und Zyklen
verhindern eine unvollständige Übergabe (Exit 1). Eltern ohne Hinweis bleiben
stumm; ihre Beschreibungen, Notizen und Kommentare werden nicht übernommen.

Beispiel: `ki-dev-ablauf-zip` bündelt die Handoff-Vorgänge. Bei
`ki-dev handoff ki-dev-ablauf-prx --step build` erscheint automatisch:

> Epic-Hinweis (ki-dev-ablauf-zip): Experimenteller „mensch-dev loop“ …

Der Hinweis wird einmal am Epic gepflegt, nicht in jedem Kind verknüpft.

### Pflichtwerte

Immer: `id`, `title`, `description` als nichtleere Strings.

| Schritt | zusätzlich |
| --- | --- |
| `map`, `graph`, `materialize` | `metadata.handoff.source_refs` |
| `build`, `review` (ohne `--review-of`, = `--review-of build`) | `acceptance_criteria`, `design` |

`build` und `review` brauchen keine Metadaten; fehlende Metadaten blockieren nur
`map`, `graph` und `materialize`. `design` soll die relevanten
Schnittstellen/Code-Einstiege und die konkreten Prüfaufträge enthalten. Das
Werkzeug prüft nur Vorhandensein und Typ, nicht die inhaltliche
Ausführungsreife.

### `--review-of`: getrenntes Review je Handoff-Schritt

`--step review` prüft standardmäßig das Ergebnis von `build`. `--review-of
map|graph|materialize|build` wählt stattdessen den Prüfgegenstand für ein
eigenes, getrenntes Review nach den jeweils vorangegangenen Schritten
`map`, `graph` und `materialize` – unabhängig vom verwendeten Modell. Die
Option ist nur zusammen mit `--step review` zulässig; jede andere Kombination
(auch mit der `map --agent`/`--session`-Form) ist Exit 2 vor jeder
`bd`-Anfrage. Ohne `--review-of` bleibt `--step review` unverändert die
bisherige Build-Review; `--review-of build` ist dazu gleichwertig.

### `--next-turn`: nächste Nachricht nach einer Korrektur

```bash
ki-dev handoff projekt-42 --step review --next-turn
ki-dev handoff projekt-42 --step review --next-turn --feedback-file rueckmeldung.txt
ki-dev handoff projekt-42 --step review --next-turn --feedback-file - < rueckmeldung.txt
```

Nach einer Korrektur erzeugt `--next-turn` die nächste Nachricht, die du selbst
übergibst; die erste Zeile nennt den Empfänger. Die Review-Nachricht ist eine
kurze Folgenachricht in die bisherige, vom Autor getrennte Review-Sitzung
(Reviewziel, Bead, Prüfauftrag, Bericht, Rückmeldung), keine zweite
Rollenübergabe; eine frische Sitzung startest du mit `--step review` ohne
`--next-turn`. Es gibt keinen eigenen
`check`-Befehl, keine Sitzungs- oder Rundenzustände und keinen Agentenstart.

| Prüfgegenstand | Ergebnis | Empfänger, stdout, Exit |
| --- | --- | --- |
| `build` (Standard) | Vorlauf fehlgeschlagen (Korrektur, Prüfung, Start, Timeout, Artefakt) | Bau-Agent: „Bitte die gemeldeten Fehler beheben. Melde anschließend nur zurück, was aus Diff und Prüfergebnissen nicht hervorgeht …“, Befund wie beim Reparaturbefund (ohne Artefaktzeile, wenn kein Artefakt entstand), Grenze für die Rückmeldung; Exit 1 |
| `build` | Vorlauf bestanden | bisherige, vom Schreibagenten getrennte Review-Sitzung: Korrekturen und betroffene Kriterien samt Regressionen fachlich erneut prüfen, `PASS \| CHANGES \| NEEDS_DECISION`, Prüfbericht beigefügt; grüne Tests sind kein Review-PASS; Exit 0 |
| `map`, `graph`, `materialize` | ohne Code-Vorlauf | dieselbe Review-Sitzung: erneute, phasengerechte Prüfung; Exit 0 |

Nur der Prüfgegenstand `build` braucht `tool.ki-dev.handoff.preflight`;
`--check-args` gilt wie bisher nur dort. Der Fortschritt des Vorlaufs steht auf
stderr, die Nachricht auf stdout (auch bei Exit 1). Ohne `--next-turn` bleibt
alles unverändert, insbesondere ist stdout bei einem Vorlauffehler leer.

`--next-turn` gilt nur mit `BEAD_ID` und `--step review`; `--feedback-file`
nur zusammen mit `--next-turn` (sonst Exit 2 vor jeder `bd`-Anfrage).

**Rückmeldung (`--feedback-file DATEI|-`):** Eine UTF-8-Datei oder, mit `-`,
stdin; beide Wege sind gleichwertig. Ohne die Option wird nichts gelesen,
auch nicht stdin. Der Text erscheint als unbestätigte Aussage des
Schreibagenten (nicht geprüft, kein Beleg, Zeilen mit `| ` zitiert,
Steuerzeichen entfernt) in beiden Nachrichten. Verlangt wird nur, was nicht aus
Diff und Prüfergebnissen hervorgeht. `bd`-Notizen und -Kommentare werden weder
gelesen noch beschrieben; es gibt keine dauerhafte Ablage.

**Grenze:** `[tool.ki-dev.handoff] feedback_max_chars` in `pyproject.toml`, eine
positive ganze Zahl (Standard 600 bei fehlender Angabe, auch ohne Datei; dieses
Projekt setzt sie ausdrücklich). Gezählt werden Unicode-Zeichen einschließlich
Leerzeichen und Zeilenumbrüchen (CRLF = 2); eingelesen werden höchstens Grenze
+ 1 Zeichen; Bytes dahinter werden weder gelesen noch dekodiert. Die
Reparaturnachricht nennt die Grenze. Mit `--next-turn` wird sie für jedes Ziel
geprüft: Ein vorhandener ungültiger Wert oder ungültiges TOML ist Exit 2, auch
für `map`/`graph`/`materialize` ohne Rückmeldung; eine fehlende
Vorlauf-Konfiguration bleibt dort erlaubt.

Eingabefehler liefern keine Übergabe und starten keinen Vorlauf: leere oder
nur aus Leerraum bestehende Rückmeldung und Überlänge (keine Kürzung) sind
Exit 2; Lese- oder UTF-8-Fehler sind Exit 1, ohne Textinhalt in der Meldung.

### `--check-args`: Prüfbefehl einmalig ergänzen

Scheitert der Vorlauf an einem unabhängigen Test, hängt `--check-args
NAME=ARGS` die Argumente einmalig an die Prüfung `NAME` an, ohne
`pyproject.toml` zu ändern:

```bash
ki-dev handoff projekt-42 --step review --check-args 'tests=-k "not langsam"'
ki-dev handoff projekt-42 --step review \
  --check-args 'tests=--deselect tests/a.py::test_x --deselect tests/b.py::test_y'
```

`ARGS` wird wie in einer Shell zerlegt und hat keine Längengrenze. Die Option
ist wiederholbar (je Prüfung einmal) und gilt nur für den Vorlauf
(`--step review`, Prüfgegenstand `build`). Exit 2 vor jeder Schreibwirkung:
fehlendes `=`, leerer Name oder leere `ARGS`, unvollständiges Quoting,
NUL/CR/LF, doppelte Prüfung, unbekannter Name oder Name einer Korrektur
(stderr nennt die vorhandenen Prüfungen). Die Ergänzung bleibt sichtbar:
Bericht und Übergabe markieren die Zeile mit `[ergänzt per --check-args]`,
das Prüfartefakt nennt sie unter `added_args`.

Die frische Sitzung startest du selbst; `handoff` startet keinen Agenten
und schließt sie nicht automatisch. Optional kannst du dafür ein anderes
Modell oder einen anderen Anbieter wählen – kein Anbieter ist
vorgeschrieben, es gibt keine automatische Übermittlung oder
Modellanfrage und **keine Garantie unabhängiger Fehler**: Ein anderes
Modell kann dieselben Lücken übersehen.

| `--review-of` | zusätzliche Pflichtfelder | deterministischer Vorlauf |
| --- | --- | --- |
| `map` | `metadata.handoff.source_refs` | nein |
| `graph` | `metadata.handoff.source_refs` | nein |
| `materialize` | `metadata.handoff.source_refs`, `acceptance_criteria`, `design` | nein |
| `build` (Standard) | `acceptance_criteria`, `design` | ja |

Nur `--review-of build` führt den
[deterministischen Vorlauf](#deterministischer-vorlauf-vor-der-review-übergabe-step-review)
aus `handoff_preflight` aus; `map`, `graph` und `materialize` sind reine,
lesende Quellenprüfungen ohne Prozessaufrufe und ohne `pyproject.toml`. Für
`materialize` gilt zusätzlich: Es reicht nicht, den fertig materialisierten
Auftrag gegen sich selbst zu prüfen – das Review vergleicht ihn gegen die
ursprünglichen, bestätigten Nutzeranforderungen und Quellen und gibt bei
fehlender Quelle `NEEDS_DECISION` statt eines Freibriefs für formal gefüllte
Felder.

Jede produktive Übergabe (`map`, `graph`, `materialize`, `build`) nennt am
Ende den passenden Review-Aufruf, z. B. nach `materialize`:

```bash
ki-dev handoff BEAD_ID --step review --review-of materialize
```

Alle vier Prüfgegenstände geben `PASS | CHANGES | NEEDS_DECISION` aus, nennen
Befunde mit Quellen-/Anforderungsbezug, konkreter Abweichung und betroffenem
Abschnitt und starten selbst weder Prüfwerkzeuge noch Folgemodelle. Ein
Review hat keine automatische Autorität gegenüber dem vorangegangenen Agenten
und schließt nichts automatisch; `PASS` gilt nur für den vom Menschen
zugeordneten Arbeitsstand/Scope, was `handoff` nicht technisch prüft, und
unentscheidbare Konflikte entscheidet der Mensch. Es gibt keine erzwungene
Review-Kette: Nach jedem produktiven Schritt folgt ein Review, nach einer
substanziellen Korrektur nur eine erneute Prüfung der betroffenen Kriterien.

### Metadatenbeispiel

```json
{"handoff": {"source_refs": ["docs/design/protokoll-a.md#L12-L40", "bd:projekt-karte"]}}
```

Setzen mit z. B.
`bd update projekt-42 --metadata '{"handoff":{"source_refs":["docs/design/protokoll-a.md#L12-L40","bd:projekt-karte"]}}'`.
`source_refs` ist eine nichtleere Liste nichtleerer Strings: relative
Dateipfade mit Fundstelle oder `bd:`-IDs. Sie werden nur als Text
weitergegeben, nicht aufgelöst und nicht auf Vollständigkeit geprüft.

## Fehlende Felder und Fehlerfälle

| Exit | Bedeutung |
| --- | --- |
| 0 | Übergabe auf stdout (bei `--step review` inklusive Prüfbericht; mit `--next-turn` die Review-Nachricht) |
| 2 | Aufruf falsch (fehlende/unbekannte Optionen, Mischung von `BEAD_ID`/`--step` mit `map --agent`/`--session`, `--review-of` ohne `--step review` oder zusammen mit `map --agent`/`--session`, `--check-args` außerhalb des Vorlaufs oder ungültig, `--next-turn` ohne `--step review`, `--feedback-file` ohne `--next-turn`, leere oder zu lange Rückmeldung, ungültige `feedback_max_chars` oder `base_max_chars`, zu lange Basisübergabe, fehlendes `map`, anderer Anbieter als `codex`, ungültige Sitzungs-ID), Bead formal unvollständig, oder bei `--step review` (Prüfgegenstand `build`) eine ungültige Vorlauf-Konfiguration (jeweils vor jeder Schreibwirkung); stderr nennt z. B. die Feldpfade `metadata.handoff.source_refs` oder `metadata.handoff.source_refs[1]` |
| 1 | Bead-Form: `bd` nicht lesbar (nicht gefunden — stderr nennt dann `Bead BEAD_ID nicht gefunden` —, Fehler, Zeitüberschreitung, unerwartete Antwort), oder bei `--step review` eine fehlgeschlagene Korrektur/Prüfung (kurzer Reparaturbefund statt Übergabe; mit `--next-turn` stattdessen die Bau-Nachricht auf stdout), nicht lesbare Rückmeldung (Datei/stdin, kein UTF-8), nicht lesbare `pyproject.toml` (Basisgrenze). Sitzungsform: Sitzung fehlt, ist mehrdeutig oder besteht die Dialogprüfung nicht; Quellen-Datei abweichend; Quellen-Bead mehrdeutig oder nicht bestätigt; `bd`-Fehler. Kurze, bereinigte Ursache auf stderr |

Bei fehlender ID, fehlendem oder unbekanntem `--step` wird `bd` nicht gestartet.
Beheben: fehlende Felder im Bead ergänzen (`bd update …`) und erneut aufrufen.

## Ablauf in wenigen Minuten

1. `map`: Übergabe ausgeben, in einer neuen Agentensitzung einfügen. Danach
   den erstellten Karten-Bead mit `--step review --review-of map` in einer
   frischen Sitzung prüfen lassen.
2. `graph`: Übergabe für den Bead der Karte; der Agent legt dünne Vorgänge an.
   Danach jeden angelegten dünnen Vorgang mit `--step review --review-of
   graph` prüfen lassen, bevor er materialisiert wird.
3. `materialize`: je dünnem Vorgang eine Sitzung; danach die Ausführungsreife
   mit `--step review --review-of materialize` getrennt prüfen lassen.
4. `build`: Übergabe des materialisierten Beads in einer Bau-Sitzung.
5. `review` (Standard bzw. `--review-of build`): Vorher läuft automatisch der
   [deterministische Vorlauf](#deterministischer-vorlauf-vor-der-review-übergabe-step-review);
   erst bei dessen Erfolg entsteht die Übergabe für eine **frische, getrennte**
   Sitzung. Der Review-Text verlangt zuerst ein eigenes Urteil anhand von
   `description`, `design`, `acceptance_criteria`, Diff und Prüfbericht und
   ein Ergebnis `PASS`, `CHANGES` oder `NEEDS_DECISION`. Das Schließen des
   Beads entscheidest du.

Die „Hinweis für den Menschen“-Zeile am Ende jeder Übergabe nennt nur den
üblichen Folgeschritt; sie wird nie automatisch ausgeführt.

## Codex-Sitzung als Quelle (`handoff map`)

```bash
ki-dev handoff map --agent codex --session SESSION_ID
```

Erschließt eine lokale Codex-Sitzung als Quelle für den Schritt `map`. Das
Positionswort `map` ist Teil des Aufrufs und das einzige erlaubte
Positionsargument. `--agent` und `--session` sind beide erforderlich; `--agent` bezeichnet den
Anbieter der **Quellsitzung** (heute nur `codex`), nicht den späteren
Kartierungsagenten. Es gibt kein Dateipfadargument und keine automatische Wahl
der letzten Sitzung. Die Form lässt sich nicht mit einer `BEAD_ID`, einem
anderen Positionsargument oder `--step` mischen; auch `--agent`/`--session`
ohne `map` wird abgelehnt (Exit 2, vor jeder Schreibwirkung).

**Sitzungsordner:** `KI_DEV_CODEX_SESSIONS_DIR` (ausdrücklicher Ordner), sonst
`CODEX_HOME/sessions`, sonst `~/.codex/sessions`. Ein gesetzter, aber leerer
Wert ist ein Fehler (mit Klartextmeldung, ohne Traceback), ebenso ein nicht
lesbarer Ordner oder eine nicht lesbare Sitzungsdatei. Die ID darf nur aus Buchstaben, Ziffern, `_` und `-`
bestehen und muss genau eine Sitzung treffen.

**Strenge Dialogprüfung:** Erwartet wird ein sauberer Wechsel aus
Benutzernachricht und `final_answer`, mit eindeutigem, endlichem `ordinal` und
passenden `turn_id`-Paaren. Ungültiges JSON (auch eine abgeschnittene letzte
Zeile), unbekannte Phasen, leere Texte oder ein unvollständiger Dialog brechen
mit Exit 1 ab; es entsteht weder Datei noch Bead. Die Meldung nennt nur
Prüfcode, Zeile und Feldpfad (höchstens 10 Fälle je Prüfung), nie
Gesprächsinhalt. Sie weist auf eine Plausibilitäts-/Formatabweichung hin, nicht
auf einen bewiesenen CLI-Versionswechsel. Es gibt kein `--force`. Für neue
Formate bleibt ein getrenntes, nicht veröffentlichtes Entwicklungswerkzeug;
seine Ausgabe gehört nicht ungefiltert in einen Agentenkontext.

**Schreibwirkungen (lokal):**

1. Das normalisierte Transkript (eine Nachricht je Zeile mit `ordinal`, `role`,
   `text`, `source_line`) wird atomar unter
   `.local/handoff/AGENT/SESSION_ID/DIGEST-PARSERVERSION.jsonl` abgelegt. Der
   Ordner ist nicht versioniert. Ein identisches Artefakt wird wiederverwendet,
   abweichender Inhalt am selben Schlüssel ist ein Fehler.
2. Ein Quellen-Bead wird über `bd list` gesucht (Schlüssel
   `metadata.handoff.source_key` aus Anbieter, Sitzung, Byte-Hash und
   Parserversion) und sonst per `bd create` angelegt. `metadata.handoff.source_refs`
   verweist auf das Artefakt; die Beschreibung nennt Quelle und Stand, aber
   keinen Gesprächsinhalt. Mehrere Treffer brechen ab.
3. Erst danach gibt der Befehl die bestehende `map`-Übergabe mit
   Quellenreferenz und Hinweis zum abschnittsweisen Lesen aus. Das Transkript
   erscheint weder auf stdout noch in Beads.

Geänderte Sitzungsbytes ergeben einen neuen Stand und einen neuen Bead; frühere
Quellen und Karten bleiben unberührt. Schlägt `bd` fehl (Exit 1), darf das
gültige Artefakt bleiben; der Wiederholungsaufruf verwendet es erneut. Nutze den
Aufruf seriell: Parallelimporte sind nicht abgesichert.

**Manuelle Fortsetzung:** Übergabe kopieren und in einer frischen
Kartierungssitzung einfügen, danach getrennt prüfen lassen. Die Karte geht mit
Wiederholungen, Präzisierungen und Widersprüchen inhaltlich um; der Parser
bereinigt nichts. Der Befehl startet keinen Agenten und legt keine Karte an,
beansprucht oder schließt nichts.

## Deterministischer Vorlauf vor der Review-Übergabe (`--step review`)

Build darf gezielt entwickeln und testen; das ist kein pauschales Test-,
Typprüfer- oder Werkzeugverbot. Ein deterministischer Vorlauf entlastet die
Bau-Sitzung nur von mechanischem Linting/Formatieren und den abschließenden
Prüfungen. Die Review-Sitzung selbst startet keine Formatter, Linter,
Typprüfer oder Tests und keine Folgemodelle; sie liest Dateien, Diff,
Anforderungen und den Prüfbericht und beurteilt anhand dessen auch Testqualität und Abdeckung.

`ki-dev handoff BEAD_ID --step review` führt diesen Vorlauf jetzt selbst aus,
**bevor** die Übergabe entsteht — das erweitert den sonst rein lesenden
Vertrag ausdrücklich für diesen einen Aufruf. Ablauf: konfigurierte
Korrekturen seriell (Abbruch bei der ersten fehlgeschlagenen; restliche
Korrekturen **und** alle Prüfungen gelten dann als ausgelassen und erscheinen
so im Bericht; bereits erfolgte Änderungen bleiben unverändert stehen, es gibt
keinen automatischen Rückbau), danach — nur wenn alle Korrekturen erfolgreich
waren — alle konfigurierten Prüfungen. Die Zuordnung der Ergebnisse zum
Arbeitsstand liegt beim Menschen; der Vorlauf erzeugt weder Fingerprints noch
Git-Snapshots und erkennt keine Änderungen zwischen Prüfungen. Er braucht
dafür auch kein Git-Repository.

**Konfiguration:** projektlokale `pyproject.toml` (Orte aller
ki-dev-Konfigurationen listet `ki-dev config`), Tabelle
`tool.ki-dev.handoff.preflight`, Listen `corrections` (darf leer sein) und
`checks` (mindestens ein Eintrag), je Eintrag `name` (eindeutig über beide
Listen), nichtleere `argv`-Liste nichtleerer Zeichenketten ohne NUL/CR/LF,
positiver endlicher `timeout_s`. Die Länge von `argv` ist nicht begrenzt;
lange Befehle kürzt nur die Ausgabe (siehe **Ausgabe**).
Keine Autodetektion, keine automatische Installation, keine impliziten
Fixes; fehlt die Tabelle oder `checks`, enthält `argv` NUL/CR/LF, oder ist
die Datei kein gültiges UTF-8/TOML, ist das ein Konfigurationsfehler (Exit 2, vor jedem
Korrekturbefehl erkannt, unabhängig davon, welcher Eintrag betroffen ist). Prozessaufrufe laufen
ohne Shell im aktuellen Arbeitsverzeichnis (Projektwurzel) mit geerbter
Umgebung. Enthält das erste `argv`-Element einen Pfadtrenner, gilt es relativ
zur Projektwurzel (`scripts/pruefe.sh`); ein Name ohne Trenner wird im aktuellen
`PATH` gesucht, und zwar genau unter diesem Namen: `pruef_werkzeug` startet
nicht ersatzweise `pruef-werkzeug`, sondern meldet ohne exakten Treffer einen
Startfehler. Kein Commit, kein Zurücksetzen, kein Agentenstart, kein
Beads-Update.

**Ausgabe:** Während des Vorlaufs meldet stderr vor jedem gestarteten
Befehl eine Fortschrittszeile (`Vorlauf: tests läuft (Timeout 360 s) …`),
damit ein langer Lauf nicht wie ein Hänger aussieht; stdout bleibt davon
frei und lässt sich weiter umleiten (`> uebergabe.txt`).
Erfolg (Exit 0) — stdout enthält nur die Übergabe, angereichert
um einen kompakten Bericht (`PRUEFBERICHT vorlauf-start=…`, je Befehl
Status, gekürzter Ausgabe und `argv` mit eindeutigem Quoting mehrteiliger
Argumente). `name` und die Prozessausgabe werden von Steuerzeichen/ANSI-Codes
bereinigt und begrenzt. `argv` wird nicht maskiert; über 100 Zeichen wird sie
einzeilig mit sichtbarer Restlänge gekürzt (`pytest --desel…(+87)…test_y`).
Vollständig steht sie im Prüfartefakt, auf das genau eine Zeile verweist
(`Vollständig: .local/handoff/preflight/<Zeitstempel>.json`) — bei Erfolg in
der Übergabe, bei Exit 1 im Reparaturbefund. Eine abschließende Hinweiszeile nennt, dass der
Zeitpunkt der manuellen Zuordnung dient und kein Beweis eines unveränderten
Quellstands ist; nach weiteren Änderungen ist der Vorlauf erneut zu starten.
Prüf- oder Ausführungsfehler (Exit 1) — stdout bleibt leer, stderr listet
jeden konfigurierten Befehl mit seinem tatsächlichen Status (auch bereits
erfolgreiche Korrekturen und wegen eines vorherigen Fehlschlags ausgelassene
Befehle), statt nur die fehlgeschlagenen zu zeigen; volle Prozesslogs
bleiben außen vor. Der Befund endet mit dem Ort der Konfiguration
(`Konfiguration: pyproject.toml [tool.ki-dev.handoff.preflight]`) und, wenn
eine Prüfung (nicht eine Korrektur) gescheitert ist, dem einmaligen Ausweg
(`Einmalig ergänzen: --check-args tests=ARGS`). Ein Prüfartefaktfehler außerhalb eines
einzelnen konfigurierten Befehls (z. B. Artefaktverzeichnis nicht schreibbar)
erscheint als eigener kurzer `Vorlauf-Ausführungsfehler` statt eines
unbehandelten Programmabbruchs; bereits gelaufene Befehle (bestanden wie
fehlgeschlagen, jeweils nicht zurückgesetzt) werden dabei mit aufgeführt,
nicht verworfen. Details stehen bei Bedarf als lokales
Prüfartefakt unter `.local/handoff/preflight/` (nicht versioniert, kein
Projektmemory).
Ungültige Konfiguration oder ein formal unvollständiger Bead (Exit 2) werden
vor dem ersten Korrekturbefehl erkannt.

Der Vorlauf gehört zum manuellen `handoff`-Ablauf. Gemeinsame Helfer dürfen
klein umstrukturiert und wiederverwendet werden, wenn Ein-/Ausgabeverträge und
Betriebsverhalten anderer Features erhalten bleiben und dies tatsächlich
Arbeit spart. Die vorhandenen Git-Helfer lesen Commit-Referenzen oder verlangen
einen sauberen Arbeitsbaum; sie ersetzen keinen Vergleich uncommitteter
Inhalte. Für diesen optionalen Schutz wird keine neue Infrastruktur gebaut.

## Grenze der Basisübergabe

Begrenzt wird nur die gerenderte Basis: Schritt/Reviewziel, Bead-ID und
-Titel, gemeinsame und Rollentexte, Epic-Hinweise, Quellenreferenzen,
Folgeschritthinweis und beim Sitzungsimport der Lesehinweis. Der gesonderte
Leitlinienblock und der Prüfbericht des Vorlaufs zählen nicht mit und bleiben
vollständig; die gesamte Ausgabe kann die Grenze daher überschreiten. Das ist
keine Tokenzusage, keine Summe von Bead-Feldern und keine zweite Definition der
Beads-Feldgrenzen.

**Grenze:** `[tool.ki-dev.handoff] base_max_chars` in `pyproject.toml`, eine
positive TOML-Ganzzahl (Standard 4000 bei fehlender Datei oder Angabe; dieses
Projekt setzt sie ausdrücklich). Gezählt werden Unicode-Zeichen des
tatsächlich ausgegebenen Basistexts einschließlich Leerzeichen,
Zeilenumbrüchen und des abschließenden Zeilenumbruchs. Gleich der Grenze ist
zulässig. `ki-dev config` zeigt den Ort.

**Übergröße:** Exit 2, stdout leer, nie gekürzt. Die Diagnose (höchstens 1000
Zeichen) nennt Ist und Grenze sowie die größten veränderlichen Anteile als
Feld- bzw. Referenzindex (`title`, `epic_context[0]`, `source_refs[1]`,
`Lesehinweis`) mit Zeichenzahl, nie deren Text; die vollständigen Quellen
bleiben im Bead. Rollen- und Gemeinsamtexte zählen mit, stehen aber nicht in
der Liste.

**Ungültige Konfiguration:** boolesche, Fließkomma-, Text- und Listenwerte,
Null und negative Zahlen, eine falsche Tabelle (`tool`, `ki-dev`,
`handoff` ist keine Tabelle) und defektes TOML oder Nicht-UTF-8 sind Exit 2;
eine nicht lesbare Datei ist Exit 1. Es gibt keinen stillen Ersatz.

**Zeitpunkt:**

- `BEAD_ID --step …`: Die Konfiguration wird vor jeder `bd`-Anfrage gelesen.
  Bei `--step review` (Prüfgegenstand `build`) wird die Basis vor dem
  Vorlauf geprüft, also vor allen Korrekturen; Leitlinien und Prüfbericht
  kommen erst danach dazu.
- `map --agent … --session …`: Die Konfiguration wird vor Quellenablage und
  Beads-Anlage geprüft. Die endgültige Basis (mit Titel und Lesehinweis)
  steht erst nach der Quellenanlage fest. Ist sie zu lang, gibt es weder
  Übergabe noch Kürzung; Quelldatei und Quellen-Bead bleiben bestehen und
  werden beim erneuten Aufruf wiederverwendet. Kein Rückbau.
- `--next-turn` ist eine Folgenachricht und behält seinen Vertrag; die
  Basisgrenze gilt dort nicht und wird nicht gelesen.

## Mitgelieferte Leitlinien

Alle Formen hängen die geltenden Regeltexte der Architektur-/Programmier-
und der Technikleitlinie sowie der Arbeitsregeln direkt an:
`BEAD_ID --step …` und `map --agent … --session …` die Regeln des Schritts,
`local` nur die allgemeinen Abschnitte (`common`). Der Agent muss Leitlinien weder suchen noch ihre
Phasenzuordnung selbst entscheiden; er wendet die mitgelieferten Texte an,
ohne ihre Quelldokumente erneut vollständig zu lesen.

**Quelle und Auswahl.** Die Regeln stehen in
`docs/policies/programmierleitlinie.de.yaml`,
`docs/policies/technikleitlinie.de.yaml` und
`docs/policies/arbeitsregeln.de.yaml` (in dieser Reihenfolge). Die
Arbeitsregeln ersetzen den früheren Einstiegstext von `AGENTS.md`/`CLAUDE.md`:
Beads lesen, Rollenrechte („Manueller Handoff“), Sitzungsende, Python/pytest und
Verbrauchsmessung; sie stehen vollständig in `common` und erreichen jede
Sitzung. Jede Datei
enthält `title`, `permalink`, `sections` (geordnete Liste `{id, text}`, Text
als Markdown-Literalblock `|-`), `common` sowie `stages` mit genau `map`,
`graph`, `materialize` und `build`, jeweils `task` und `review` als
ID-Listen. Ausgewählt wird fest, ohne Modell oder Themenklassifikation:
`common` + `stages[ZIEL].task`; bei `--step review` zusätzlich
`stages[ZIEL].review`. ZIEL ist der Schritt oder `--review-of`; ohne
`--review-of` bleibt es `build`. Reihenfolge wie in `sections`, jede ID je
Datei einmal, auch wenn sie mehrfach zugeordnet ist. Die Zuordnung verringert
die Geltung nicht: Allgemeine Regeln stehen in `common` und erreichen jeden
Schritt; `stages` tragen nur die Phasenschwerpunkte (Architektur in Planung
und Materialisierung für graph/materialize, Programmierung in Umsetzung und
Review sowie Docstrings für build).

**Ausgabe.** Der Block `LEITLINIEN (mitgeliefert; …)` steht nach allen
Teilen der Basisübergabe: nach dem Hinweis für den Menschen, beim map-Import
nach dem Lesehinweis, bei der Build-Review nach dem `PRUEFBERICHT`. Jeder
Abschnitt beginnt mit `--- YAML-DATEI#ABSCHNITTS-ID ---`; Zeilenumbrüche,
Listen und Codeblöcke bleiben erhalten. Der Block ist ein gesondert
ausgewiesener Kontextblock wie der Prüfbericht: Er wird nie gekürzt und zählt
nicht zu einer Längengrenze der Basisübergabe. Die gesamte Ausgabe kann
deshalb deutlich länger sein als die Basisübergabe. Das ist keine
Tokenersparnis und keine Verbrauchszusage. `--next-turn` hängt keine
Leitlinien erneut an; die Sitzungen haben sie bereits erhalten.

**Fehler.** Die Quellen werden relativ zum aktuellen Verzeichnis geladen,
ohne Ersatzquelle, und vor Vorlauf, Quellenablage und Beads-Anlage geprüft.
Fehlende oder unlesbare Datei: Exit 1. Kein UTF-8, ungültiges YAML oder
Vertragsverletzung (Typ, leerer Text, fehlendes oder unbekanntes Feld,
doppelte oder unbekannte Abschnitts-ID): Exit 2. Diagnosen nennen Datei,
Feldpfad und ggf. Zeile, nie Regeltexte.

**Pflegeweg.** Regeln nur in den YAML-Dateien ändern, dann
`./.venv/bin/python scripts/render-guidelines.py` ausführen. Das Skript
erzeugt daraus vollständig `docs/programmierleitlinie.de.md`,
`docs/technikleitlinie.de.md` und `docs/arbeitsregeln.de.md` (Frontmatter, Permalink, Überschriften und damit
Anker bleiben erhalten; eine Kopfzeile kennzeichnet die Seite als generiert).
`--check` schreibt nichts und endet bei Abweichung mit Exit 1. `handoff`
selbst erzeugt keine Dokumentationsdateien.

**Arbeit ohne `handoff`.** `AGENTS.md` und `CLAUDE.md` sind leer. Sitzungen
ohne Bead beginnen mit `ki-dev handoff local`; wer ganz ohne Übergabe arbeitet,
liest die erzeugten Seiten `docs/programmierleitlinie.de.md`,
`docs/technikleitlinie.de.md` und `docs/arbeitsregeln.de.md`; deren Inhalt ist
derselbe.

## `AGENTS.md`/`CLAUDE.md` leer und lokal geschützt

Die Einstiegstexte stehen nur noch in `docs/policies/*.de.yaml`; die beiden
Dateien sind im Repository leer. Git transportiert keinen Schreibschutz (kein
`0444` im Klon). Nach jedem frischen Klon einmal (das Skript braucht nur die
Standardbibliothek; vor dem Anlegen der Projekt-venv genügt ein beliebiges
Python 3, danach die venv wie sonst im Projekt):

```bash
./.venv/bin/python scripts/protect-agent-files.py          # chmod 0444, nur für leere Dateien
./.venv/bin/python scripts/protect-agent-files.py --check  # leer und schreibgeschützt? (Exit 1: nein)
```

Das Skript fasst nur diese zwei Dateien im Klon an, ruft keine Fremdprogramme
auf und ändert keine globale Konfiguration. Schutz aufheben:
`chmod u+w AGENTS.md CLAUDE.md`.

**Wirkung von `bd init`/`bd setup` (bd 1.3.0, geprüft in Wegwerfklons mit
eigenem `HOME`/`CODEX_HOME`, ohne `origin`, Git-Identität per Umgebung).**
Der Schreibschutz hält sie nicht auf:

- `bd setup codex` und `bd setup claude` schreiben den Beads-Block trotz `0444`
  in die Datei (Mode danach `0644`, nicht leer).
- `bd init --non-interactive --prefix P` (mit Hooks, ohne `--skip-agents`) tut
  dasselbe; die Meldung „open AGENTS.md: permission denied“ betrifft nur einen
  Teilschritt, die Datei wird dennoch neu geschrieben. Zusätzlich legt es
  `.claude/` und `.cursor/` an und committet selbst (`bd init: initialize
  beads issue tracking`), darin die wieder befüllten `AGENTS.md` und
  `CLAUDE.md`.
- `bd init --non-interactive --prefix P --skip-agents` lässt beide Dateien
  unverändert (leer, `0444`) und legt sie auch nicht in seinen Commit. Es
  committet trotzdem seine Änderungen an `.gitignore`, `.beads/.gitignore` und
  `.beads/hooks/*` und setzt lokal `core.hooksPath`; das gilt auch ohne
  Schreibschutz und ist hier nicht Gegenstand.
- Nicht geprüft: Wirkung der Beads-Git-Hooks nach späteren
  Checkouts/Merges auf diese Dateien.

Verwende daher `bd init --skip-agents` und starte `bd setup codex|claude` nicht
in diesem Klon. Ist es passiert, meldet `--check` die nicht leere Datei. Ohne Commit mit
`git checkout -- AGENTS.md CLAUDE.md` zurücksetzen; hat `bd init` sie schon
committet, aus dem Stand davor mit `git checkout COMMIT_VOR_INIT -- AGENTS.md
CLAUDE.md` wiederherstellen. Danach das Skript erneut ausführen. Auch mit
wieder befülltem Beads-Block gehen die Rollenrechte der Übergabe vor
(Abschnitt „Manueller Handoff“ der Arbeitsregeln).

## Grenzen

- `handoff` übernimmt weder `notes` noch `comments` noch vollständige
  `description`/`design`-Texte in die Ausgabe. Das filtert nur die Ausgabe: Es
  ist keine technische Zugriffssperre, die Agentensitzung kann den Bead selbst
  lesen.
- Kein Verbrauchsschutz: Der Befehl überwacht weder Kontext noch Kosten noch
  Kontingente und gibt keine Sicherheitsgarantie. Wie lange und wie viel ein
  Agent arbeitet, steuerst du in der jeweiligen Sitzung.
- Keine Schrittwahl, Statusverwaltung, Claims oder Schließungen und keine
  Agentenstarts.
- Nur Codex-Sitzungen; ein Claude-Transkriptfilter existiert nicht.
