# Manuelle Arbeitsübergaben mit `ki-dev handoff`

`ki-dev handoff BEAD_ID --step STEP` prüft einen Bead formal und gibt eine
kurze, kopierbare Arbeitsübergabe aus. Du startest die passende Agentensitzung
selbst und fügst den Text dort ein. Der Befehl liest nur
(`bd --readonly show BEAD_ID --json` im aktuellen Arbeitsverzeichnis, Frist
10 s), schreibt nichts und startet keinen Agenten.

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
| 0 | Übergabe auf stdout |
| 2 | Aufruf unvollständig oder Bead formal unvollständig; stderr nennt die Feldpfade, z. B. `metadata.handoff.source_refs` oder `metadata.handoff.source_refs[1]` |
| 1 | `bd` nicht lesbar (nicht gefunden, Fehler, Zeitüberschreitung, unerwartete Antwort); kurze Ursache auf stderr |

Bei fehlender ID, fehlendem oder unbekanntem `--step` wird `bd` nicht gestartet.
Beheben: fehlende Felder im Bead ergänzen (`bd update …`) und erneut aufrufen.

## Ablauf in wenigen Minuten

1. `map`: Übergabe ausgeben, in einer neuen Agentensitzung einfügen. Danach
   eine getrennte Kartenprüfung starten.
2. `graph`: Übergabe für den Bead der Karte; der Agent legt dünne Vorgänge an.
3. `materialize`: je dünnem Vorgang eine Sitzung; danach die Ausführungsreife
   getrennt prüfen lassen.
4. `build`: Übergabe des materialisierten Beads in einer Bau-Sitzung.
5. `review`: Übergabe in einer **frischen, getrennten** Sitzung. Der Review-Text
   verlangt zuerst ein eigenes Urteil anhand von `description`, `design`,
   `acceptance_criteria`, Diff und selbst nachvollzogenen Prüfungen und ein
   Ergebnis `PASS`, `CHANGES` oder `NEEDS_DECISION`. Das Schließen des Beads
   entscheidest du.

Die „Hinweis für den Menschen“-Zeile am Ende jeder Übergabe nennt nur den
üblichen Folgeschritt; sie wird nie automatisch ausgeführt.

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
