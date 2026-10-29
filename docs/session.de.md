# Sitzungen als Snapshot (`ki-dev session`)

`ki-dev session` archiviert lokale Codex- und Claude-Sitzungen als datierte
JSONL-Snapshots. Mit einem Zeitraum werden alle passenden Sitzungen aus den
konfigurierten Rohsitzungsordnern ergänzt:

```bash
ki-dev session transcript --since 2026-10-01 --until 2026-10-28
```

stdout enthält je Sitzung den Snapshot-Pfad; stderr zeigt die Bilanz.
Identische Stände werden wiederverwendet, neue Stände zusätzlich abgelegt.
Der Zielordner ist `.local/var/transcripts/`. Der Aufruf braucht keinen Titel.

`session list` zeigt die neuesten Sitzungen beider Anbieter nummeriert. Die
Nummer wählt eine Sitzung für `show` und `export`. Automatische Bau- und
Review-Aufträge sowie bekannte Testsitzungen werden standardmäßig
ausgeblendet. Die Suche nach Inhalten und Listen zuletzt angesehener Sitzungen
sind noch nicht enthalten. Eine Sitzung lässt sich auch gezielt per ID ablegen:

```bash
ki-dev session transcript 0de11ef0-1ad2-48ad-af5c-45fa89e5ecab --agent claude --title 'Zustandstabelle'
# .local/var/transcripts/261005T22_zustandstabelle_0de11ef0.jsonl
```

Die Sitzungsordner und die Dialogprüfung sind dieselben wie bei
[`step map`](step.de.md#sitzung-als-quelle-step-map). Beide Aufrufe
verwenden denselben Serializer und denselben Speicher.

## Zeitraum und Quellen

`--since` schließt die untere Grenze ein. Ein Datum (`YYYY-MM-DD`) beginnt um
00:00 UTC. `--until` mit Datum schließt den ganzen UTC-Tag ein; ein genauer
ISO-Zeitpunkt mit Zeitzone ist dagegen eine ausgeschlossene obere Grenze.
Beispiel: `--since 2026-10-28T10:00:00+02:00 --until 2026-10-28T12:00:00Z`.
Ein Zeitpunkt ohne Zeitzone und ein umgekehrter Zeitraum sind Aufruffehler.

Ausgewählt wird nach **letzter protokollierter Aktivität** (`last_activity_at`),
nicht nach Sitzungsbeginn oder Dateiänderungszeit. Eine früher begonnene,
im Zeitraum zuletzt aktive Sitzung wird vollständig archiviert. Fehlt eine
belegte Aktivitätszeit, wird sie bei einer Zeitraumwahl als Fehler gemeldet.
`--all` archiviert ohne Zeitgrenze. Der Sammelexport hat kein Listenlimit;
`--agent codex` beziehungsweise `--agent claude` begrenzt den Anbieter.

Vor der Dialogprüfung werden die Zeitstempel der Rohzeilen eingegrenzt.
Liegt dieser gesamte Bereich außerhalb des Zeitraums, zählt die Sitzung als
„außerhalb“, auch wenn ihr Dialog leer oder unbrauchbar ist. Steuerereignisse
können den Bereich erweitern; bei einer möglichen Überschneidung entscheidet
weiterhin die normalisierte letzte Aktivität. Sind Rohzeiten nicht bestimmbar
oder Zeilen beschädigt, bleibt die volle Prüfung mit sichtbaren Fehlern nötig.
Die Dateiänderungszeit dient nicht zum Ausschluss, da Kopien oder
wiederhergestellte Dateien abweichende Zeiten haben können.

Der Sammelexport lädt die Projektkonfiguration einmal und verwendet die
gefundenen Dateipfade direkt. Historische Rohdateien werden für die
Zeitprüfung weiterhin gelesen; eine Dialogvalidierung und das Hashen sind
nur für mögliche Treffer nötig.

Die Projektdatei `pyproject.toml` kann Quellen und zusätzliche auszublendende
Arbeitsverzeichnisse festlegen. Relative Pfade beziehen sich auf das aktuelle
Projektverzeichnis; `~` wird aufgelöst. `ki-dev config` nennt diesen Abschnitt:

```toml
[tool.ki-dev.session]
codex_sessions_dir = "/pfad/zu/codex/sessions"
claude_sessions_dir = "/pfad/zu/claude/projects"
exclude_cwd = ["/pfad/testlaeufe/*"]
```

Explizite Umgebungsvariablen haben Vorrang: Codex liest zuerst
`KI_DEV_CODEX_SESSIONS_DIR`, dann `CODEX_HOME/sessions`, dann den Projektwert,
sonst `~/.codex/sessions`. Claude liest `KI_DEV_CLAUDE_SESSIONS_DIR`, dann den
Projektwert, sonst `~/.claude/projects`. Ungültige Konfiguration wird gemeldet.
Diese Quellen gelten auch für direkte ID-Aufrufe und `step map`.

Ein Sammelexport setzt nach einzelnen Lese- oder Speicherfehlern fort. Er
meldet Anbieter, Sitzungs-ID und Diagnose auf stderr und endet bei mindestens
einem solchen Fehler mit Exit 1. Erfolgreiche Snapshots bleiben erhalten.

## Automatische Sitzungen ausblenden

Liste, Nummernauswahl und Sammelexport verwenden denselben Filter **vor** dem
Listenlimit. Er erkennt im Rohvorspann die von ki-dev erzeugten Bau- und
Review-Aufträge, Codex-Subagenten sowie Arbeitsverzeichnisse unter
`pytest-of-*`, `readme-check` und `readme-walkthrough`. `exclude_cwd` ergänzt
diese Verzeichnismuster (`*` und `?` als Platzhalter).

Damit werden auch automatische Claude-Aufträge ausgeblendet, deren
SDK-Herkunft die spätere Dialogprüfung ablehnt. SDK-/exec-Herkunft allein und
ein beliebiges temporäres Arbeitsverzeichnis reichen nicht zum Ausblenden.
Unbekannte oder beschädigte Vorspänne bleiben zur sichtbaren Prüfung erhalten.

`--include-tests` nimmt die ausgeblendeten Sitzungen wieder in die Auswahl
auf. Bei `show -n` und `export -n` muss dieselbe Option wie bei `list` gelten:

```bash
ki-dev session list 20 --include-tests
ki-dev session show -n 2 --include-tests
ki-dev session transcript --since 2026-10-01 --include-tests
```

Ein direkter ID-Aufruf bleibt unabhängig vom Filter möglich. Der Filter
ändert oder löscht keine Rohsitzungen oder bereits gespeicherten Snapshots.

## Datierte JSONL-Snapshots

**Name:** ohne Titel `YYMMDDTHH_agent_sid8.jsonl`, mit Titel weiterhin
`YYMMDDTHH_titel_sid8.jsonl`. Der Anbieter ersetzt nur das Dateinamensegment;
es wird kein Ersatztitel gespeichert.

| Teil | Herkunft | Beispiel |
|---|---|---|
| `YYMMDDTHH` | Sitzungsbeginn (`started_at`) in UTC; nur 2000–2099 | `261005T22` |
| `titel` | Slug aus `--title`: klein, `ä→ae`, `ß→ss`, sonst `-`; höchstens 40 Zeichen | `zustandstabelle` |
| `sid8` | erste 8 Zeichen der Sitzungs-ID | `0de11ef0` |

Der genaue Zeitpunkt steht im Kopf. Fehlt der belegte Sitzungsbeginn, endet
der Aufruf mit Exit 1. Ein Export- oder Dateidatum wird nicht als Ersatz
eingesetzt. `--title` ist optional. Ein angegebener Titel muss nichtleerer
Text mit höchstens 120 Zeichen sein und Buchstaben oder Ziffern enthalten.
Ohne Titel steht `"title": null` im Kopf. Der Titel wird nie aus dem
Prompttext abgeleitet. `step map` verlangt weiterhin einen Titel für die
Quellenübergabe.

**Inhalt:** Zeile 1 ist genau ein Kopf, danach folgt eine Nachricht je Zeile.

```json
{"type": "transcript_meta", "version": 1, "agent": "claude", "session_id": "0de11ef0-…", "started_at": "2026-10-05T22:24:18.979Z", "last_activity_at": "…", "title": "Zustandstabelle", "source_digest": "…64 hex…", "parser_version": "claude-dialog-1", "diagnostics": {}}
{"type": "message", "position": 1, "ordinal": null, "role": "user", "text": "…", "source_line": 3, "timestamp": "…"}
```

Das Schema (`session_snapshot.py`, Draft 2020-12) prüft „erst der Kopf, dann
nur Nachrichten“ mit `prefixItems`/`items`. Die Feldregeln der Nachrichten
stammen aus dem gemeinsamen Transkriptvertrag (`session_transcript.py`). Ein
Kopf an einer anderen Stelle ist ein Fehler.

**Identität und Wiederholung:** Die Identität eines Snapshots besteht aus
`agent`, `session_id`, `source_digest` und `parser_version`. Titel und
Dateiname gehören nicht dazu.

- Gleicher Stand: Die vorhandene Datei wird wiederverwendet, auch bei
  anderem Titel.
- Neuer Quellstand derselben Sitzung: Er erhält ein Suffix vor `.jsonl`, zum
  Beispiel `…_0de11ef0-3fa2b9c1.jsonl`. Ist das Suffix schon belegt, wird es
  deterministisch verlängert (8, 12, 16, 24, 32 oder 64 Zeichen des Digests).
- Gleiche Identität mit abweichendem Inhalt ist ein Fehler.
- Vorhandene Dateien werden nie überschrieben. Die Datei wird zuerst
  temporär geschrieben und dann per `os.link` veröffentlicht. Ein Fehler
  hinterlässt keine scheinbar fertige Datei.

**Ort:** Standard ist `.local/var/transcripts/` im Projekt. Der Ordner ist
nicht versioniert, weil Snapshots Gesprächsinhalte enthalten. `--dir ORDNER`
wählt einen anderen Ordner.

## Ältere Formate

Gelesen wird ausdrücklich nur ein bekanntes Altformat. Andere Formate werden
mit ihren Schlüsseln abgelehnt, ohne Werte auszugeben. Bestände werden nicht
umbenannt oder konvertiert.

| Format | Ort | Schlüssel je Zeile | Behandlung |
|---|---|---|---|
| `handoff-v0` | `.local/handoff/AGENT/SESSION_ID/DIGEST-PARSER.jsonl` | `position, ordinal, role, text, source_line, timestamp` | lesbar; Identität aus dem Pfad, Titel und Zeiten bleiben leer |
| Auszugsformat A | Codex-Sitzungen 01a08147 und 01a09aef (nicht veröffentlicht) | Index-Zeilen eines Sitzungsarchivs (`document_id`, `message_role`, …) | nur inventarisiert |
| Auszugsformat B | Codex-Sitzungen 01a0c2f9 und 01a0cf85 (nicht veröffentlicht) | `ordinal, role, text` | nur inventarisiert |
| Auszugsformat C | Claude-Sitzungen cc0227f9, d1926e71 und 64d6eb11, Codex-Sitzung 01a0fc40 (nicht veröffentlicht) | `role, text, timestamp` | nur inventarisiert |

Frühere Quellen-Beads mit Verweis auf `handoff-v0` bleiben für `step map`
gültig, solange die Datei vorhanden ist.

## Aufrufe und Schreibwirkungen

| Aufruf | Wirkung |
|---|---|
| `session transcript ID --agent A [--title T] [--dir D]` | schreibt einen Snapshot und gibt seinen Pfad aus |
| `session transcript --since DATUM [--until DATUM] [--agent A] [--dir D] [--include-tests]` | ergänzt alle passenden Sitzungen im Archiv |
| `session transcript --all [--agent A] [--dir D] [--include-tests]` | ergänzt alle Sitzungen nach Filter ohne Zeitgrenze |
| `session list [ANZAHL] [--agent A] [--include-tests]` | listet die neuesten Sitzungen nummeriert mit Vorschau und schreibt nichts |
| `session show -n NR [--agent A] [--include-tests] [--pager]` | zeigt Eintrag NR der Liste an |
| `session export -n NR [--agent A] [--include-tests] --format …` | dasselbe als Export |
| `session show ID --agent A [--pager]` | zeigt die Rohsitzung an und schreibt nichts |
| `session show --snapshot DATEI [--pager]` | zeigt einen gespeicherten Snapshot an (auch `handoff-v0`) |
| `session export ID --agent A --format markdown\|jsonl [--title T] [--output DATEI]` | Ausgabe auf stdout oder in eine **neue** Datei; kein Archiv |
| `session export --snapshot DATEI --format …` | dasselbe aus einem Snapshot |

```bash
ki-dev session show 0de11ef0-1ad2-48ad-af5c-45fa89e5ecab --agent claude --pager
ki-dev session export --snapshot .local/var/transcripts/261005T22_zustandstabelle_0de11ef0.jsonl --format markdown > zustandstabelle.md
```

**Liste:** `list` führt ohne `--agent` alle Anbieter zusammen (Standard:
10 Einträge, `ANZAHL` ändert das). Je Eintrag stehen Nummer, Anbieter, letzte
Aktivität (lokale Zeit, aus dem Transkript; fehlt sie, `—`), die ganze
Sitzungs-ID und eine Vorschau: je der Anfang (60 Zeichen, einzeilig) des
ersten Mensch- und des ersten Agent-Beitrags. Die Reihenfolge folgt der
Änderungszeit der Sitzungsdatei, bei Gleichstand Anbieter und ID. Unterordner
(Subagenten) und Dateien ohne erkennbaren Sitzungsnamen zählen nicht. Eine
nicht lesbare Sitzung erscheint als Zeile `nicht verwendbar: …` mit Prüfcodes,
nie mit Inhalt. Zunächst werden nur die Dateireferenzen sortiert. Danach
werden die Vorspänne geprüft, bis die gewünschte Anzahl nach Filter erreicht
ist; ältere Sitzungen müssen dafür nicht geöffnet werden.

Die Ordner sind dieselben wie bei `show` und dem Sammelexport (siehe
[Zeitraum und Quellen](#zeitraum-und-quellen)). Fehlt ein Ordner, meldet `list` das als Hinweis auf
stderr; mit ausdrücklichem `--agent` ist es ein Fehler (Exit 1).

```bash
ki-dev session list 5
ki-dev session show -n 2 --pager
```

`-n NR` gilt für die Liste zum Zeitpunkt des Aufrufs, mit demselben `--agent`
und `--include-tests` wie bei `list`. Neue Sitzungen verschieben die Nummern; die ID in der Liste
bleibt stabil. `-n` lässt sich nicht mit `SESSION_ID` oder `--snapshot`
mischen (Exit 2); eine zu große Nummer ist Exit 1. Die Nummer ist an keinen
gespeicherten Listenstand gebunden. Für eine feste Auswahl über mehrere
Aufrufe die angezeigte Sitzungs-ID mit `--agent` verwenden.

**Anzeige:** `show` gibt Titel, Anbieter, Sitzung und Zeiten einmal aus
(fehlende Zeiten als `—`). Danach folgt je Beitrag eine Linie mit Position,
Rolle (`Mensch`/`Agent`) und Zeit, darunter der Text als Markdown. Die
Kopfzeile eines Snapshots erscheint nie als Beitrag. Ohne gespeicherten Titel
steht `AGENT-Sitzung ID` an seiner Stelle.

**Pager:** `--pager` verwendet den eingebauten Pager von Rich
(`Console.pager`, intern `pydoc.pager`). Er startet `$MANPAGER`, `$PAGER` oder
`less`. Für `less` ergänzt `ki-dev` für die Dauer der Anzeige `LESS=-R`, damit
Farben ankommen; ein vorhandenes `-R`/`-r` bleibt unverändert. Ist die Ausgabe
umgeleitet (`| head`, Datei), startet kein Pager: Die Ausgabe ist ungekürzt
und ohne Farbcodes. Schließt der Leser früh (`q` im Pager, `| head`), endet
der Aufruf ohne Fehlermeldung. Start- und Exitfehler des Pagers meldet die
Shell. Das ist eine dokumentierte Ausnahme zur
[Technikleitlinie](technikleitlinie.de.md#ausnahmen).

**Export:** `jsonl` folgt dem Snapshot-Vertrag. Der Titel kommt aus
`--title` oder aus dem gespeicherten Snapshot; fehlen beide, bleibt er im
JSONL-Kopf `null`. `markdown` enthält denselben Transkriptinhalt (`# Titel`, dann
`## Position Rolle · Zeit` je Beitrag). stdout enthält nur die Daten,
Diagnosen gehen nach stderr. `--output` legt nur eine neue Datei an; eine
vorhandene Datei bleibt unverändert (Exit 1).

Exitcodes: `0` Erfolg; `1` Sitzung oder Snapshot nicht verwendbar (die
Meldung nennt nur Prüfcode, Zeile und Feldpfad); `2` falscher Aufruf
(Anbieter, ID, Titel, Format oder gemischte Auswahl), vor jedem
Dateizugriff.
