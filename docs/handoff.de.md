# Manuelle Arbeitsübergaben mit `ki-dev handoff`

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

## Pflichtfelder je Schritt

Immer: `id`, `title`, `description` als nichtleere Strings.

| Schritt | zusätzlich |
| --- | --- |
| `map`, `graph`, `materialize` | `metadata.handoff.source_refs` |
| `build`, `review` | `acceptance_criteria`, `design` |

`build` und `review` brauchen keine Metadaten; fehlende Metadaten blockieren nur
`map`, `graph` und `materialize`. `design` soll die relevanten
Schnittstellen/Code-Einstiege und die konkreten Prüfaufträge enthalten. Das
Werkzeug prüft nur Vorhandensein und Typ, nicht die inhaltliche
Ausführungsreife.

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
| 0 | Übergabe auf stdout (bei `--step review` inklusive Prüfbericht) |
| 2 | Aufruf falsch (fehlende/unbekannte Optionen, Mischung von `BEAD_ID`/`--step` mit `map --agent`/`--session`, fehlendes `map`, anderer Anbieter als `codex`, ungültige Sitzungs-ID), Bead formal unvollständig, oder bei `--step review` eine ungültige Vorlauf-Konfiguration (jeweils vor jeder Schreibwirkung); stderr nennt z. B. die Feldpfade `metadata.handoff.source_refs` oder `metadata.handoff.source_refs[1]` |
| 1 | Bead-Form: `bd` nicht lesbar (nicht gefunden, Fehler, Zeitüberschreitung, unerwartete Antwort), oder bei `--step review` eine fehlgeschlagene Korrektur/Prüfung (kurzer Reparaturbefund statt Übergabe). Sitzungsform: Sitzung fehlt, ist mehrdeutig oder besteht die Dialogprüfung nicht; Quellen-Datei abweichend; Quellen-Bead mehrdeutig oder nicht bestätigt; `bd`-Fehler. Kurze, bereinigte Ursache auf stderr |

Bei fehlender ID, fehlendem oder unbekanntem `--step` wird `bd` nicht gestartet.
Beheben: fehlende Felder im Bead ergänzen (`bd update …`) und erneut aufrufen.

## Ablauf in wenigen Minuten

1. `map`: Übergabe ausgeben, in einer neuen Agentensitzung einfügen. Danach
   eine getrennte Kartenprüfung starten.
2. `graph`: Übergabe für den Bead der Karte; der Agent legt dünne Vorgänge an.
3. `materialize`: je dünnem Vorgang eine Sitzung; danach die Ausführungsreife
   getrennt prüfen lassen.
4. `build`: Übergabe des materialisierten Beads in einer Bau-Sitzung.
5. `review`: Vorher läuft automatisch der
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
Typprüfer oder Tests; sie liest Dateien, Diff, Anforderungen und den
Prüfbericht und beurteilt anhand dessen auch Testqualität und Abdeckung.

`ki-dev handoff BEAD_ID --step review` führt diesen Vorlauf jetzt selbst aus,
**bevor** die Übergabe entsteht — das erweitert den sonst rein lesenden
Vertrag ausdrücklich für diesen einen Aufruf. Ablauf: konfigurierte
Korrekturen seriell (Abbruch bei der ersten fehlgeschlagenen; restliche
Korrekturen **und** alle Prüfungen gelten dann als ausgelassen und erscheinen
so im Bericht; bereits erfolgte Änderungen bleiben unverändert stehen, es gibt
keinen automatischen Rückbau), danach — nur wenn alle Korrekturen erfolgreich
waren — alle konfigurierten Prüfungen auf demselben Stand. Ein Fingerprint des
Quellstands (Git-HEAD plus Inhalt aller uncommitteten/unversionierten
Dateien, ausgewertet aus NUL-separierter `git status -z`-Ausgabe, damit auch
zitierte Pfade und Rename-Einträge korrekt erkannt werden) wird vor und nach
den Prüfungen verglichen; weicht er ab, gilt der Bericht als ungültig, auch
wenn jede Prüfung für sich bestanden hat. Lässt sich die Git-Ausgabe nicht
verlustfrei als UTF-8 dekodieren (z. B. bei Dateinamen mit ungültigen
Bytes), scheitert der Fingerprint kontrolliert statt Pfade lautlos zu
ersetzen — das würde unterschiedliche Zustände auf denselben Fingerprint
abbilden können.

**Konfiguration:** projektlokale `pyproject.toml`, Tabelle
`tool.ki-dev.handoff.preflight`, Listen `corrections` (darf leer sein) und
`checks` (mindestens ein Eintrag), je Eintrag `name` (eindeutig über beide
Listen), nichtleere `argv`-Liste ohne NUL-Zeichen, positiver endlicher
`timeout_s`. Keine Autodetektion, keine automatische Installation, keine
impliziten Fixes; fehlt die Tabelle oder `checks`, oder enthält `argv` ein
NUL-Zeichen, ist das ein Konfigurationsfehler (Exit 2, vor jedem
Korrekturbefehl erkannt, unabhängig davon, welcher Eintrag betroffen ist).
Prozessaufrufe laufen ohne Shell im aktuellen Arbeitsverzeichnis
(Projektwurzel) mit geerbter Umgebung. Kein Commit, kein Zurücksetzen, kein
Agentenstart, kein Beads-Update.

**Ausgabe:** Erfolg (Exit 0) — stdout enthält nur die Übergabe, angereichert
um einen kompakten Bericht (`PRUEFBERICHT git=…`, je Befehl Status, gekürzte
Ausgabe und `argv`; `name`/`argv` werden dabei ebenso von Steuerzeichen/
ANSI-Codes bereinigt und begrenzt wie die Prozessausgabe, mit eindeutigem
Quoting mehrteiliger Argumente. Ein Inline-Skript nach `-c` erscheint nur
als Zeichenzahl, nie im Klartext — längere Prüflogik gehört in
referenzierte Skriptdateien; die vollständige `argv` steht bei Bedarf im
lokalen Prüfartefakt).
Prüf- oder Ausführungsfehler (Exit 1) — stdout bleibt leer, stderr listet
jeden konfigurierten Befehl mit seinem tatsächlichen Status (auch bereits
erfolgreiche Korrekturen und wegen eines vorherigen Fehlschlags ausgelassene
Befehle), statt nur die fehlgeschlagenen zu zeigen; volle Prozesslogs
bleiben außen vor. Ein Git- oder Prüfartefaktfehler außerhalb eines
einzelnen konfigurierten Befehls (z. B. kein Git-Repository,
Artefaktverzeichnis nicht schreibbar, nicht dekodierbare Git-Ausgabe)
erscheint als eigener kurzer `Vorlauf-Ausführungsfehler` statt eines
unbehandelten Programmabbruchs; bereits gelaufene Befehle (bestanden wie
fehlgeschlagen, jeweils nicht zurückgesetzt) werden dabei mit aufgeführt,
nicht verworfen. Details stehen bei Bedarf als lokales
Prüfartefakt unter `.local/handoff/preflight/` (nicht versioniert, kein
Projektmemory).
Ungültige Konfiguration oder ein formal unvollständiger Bead (Exit 2) werden
vor dem ersten Korrekturbefehl erkannt.

`ki-dev loop` ist von diesem Vorlauf unverändert; er gehört ausschließlich zum
manuellen `handoff`-Ablauf.

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
