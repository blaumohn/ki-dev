# Sitzungen als Snapshot (`ki-dev session`)

`ki-dev session` liest eine lokale Codex- oder Claude-Sitzung per
**expliziter ID und Anbieter** und legt sie als datierten JSONL-Snapshot ab.
Die Suche nach Sitzungen und Listen zuletzt angesehener Sitzungen sind noch
nicht enthalten.

```bash
ki-dev session transcript SESSION_ID --agent claude --title 'Docker-Schicht'
# .local/var/transcripts/261002T14_docker-schicht_0de11ef0.jsonl
```

Die Sitzungsordner und die Dialogprüfung sind dieselben wie bei
[`step map`](handoff.de.md#sitzung-als-quelle-step-map). Beide Aufrufe
verwenden denselben Serializer und denselben Speicher.

## Datierte JSONL-Snapshots

**Name:** `YYMMDDTHH_titel_sid8.jsonl`

| Teil | Herkunft | Beispiel |
|---|---|---|
| `YYMMDDTHH` | Sitzungsbeginn (`started_at`) in UTC; nur 2000–2099 | `261002T14` |
| `titel` | Slug aus `--title`: klein, `ä→ae`, `ß→ss`, sonst `-`; höchstens 40 Zeichen | `docker-schicht` |
| `sid8` | erste 8 Zeichen der Sitzungs-ID | `0de11ef0` |

Der genaue Zeitpunkt steht im Kopf. Fehlt der belegte Sitzungsbeginn, endet
der Aufruf mit Exit 1. Ein Export- oder Dateidatum wird nicht als Ersatz
eingesetzt. `--title` ist Pflicht: nichtleerer Text mit höchstens 120 Zeichen,
der Buchstaben oder Ziffern enthält. Der Titel wird nie aus dem Prompttext
abgeleitet.

**Inhalt:** Zeile 1 ist genau ein Kopf, danach folgt eine Nachricht je Zeile.

```json
{"type": "transcript_meta", "version": 1, "agent": "claude", "session_id": "0de11ef0-…", "started_at": "2026-10-02T14:05:00Z", "last_activity_at": "…", "title": "Docker-Schicht", "source_digest": "…64 hex…", "parser_version": "claude-dialog-1", "diagnostics": {}}
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
| Auszugsformat A | Codex-Sitzungen 01a08147 und 01a09aef | Index-Zeilen eines Sitzungsarchivs (`document_id`, `message_role`, …) | nur inventarisiert |
| Auszugsformat B | Codex-Sitzungen 01a0c2f9 und 01a0cf85 | `ordinal, role, text` | nur inventarisiert |
| Auszugsformat C | Claude-Sitzungen cc0227f9, d1926e71 und 64d6eb11, Codex-Sitzung 01a0fc40 | `role, text, timestamp` | nur inventarisiert |

Frühere Quellen-Beads mit Verweis auf `handoff-v0` bleiben für `step map`
gültig, solange die Datei vorhanden ist.

## Aufrufe und Schreibwirkungen

| Aufruf | Wirkung |
|---|---|
| `session transcript ID --agent A --title T [--dir D]` | schreibt einen Snapshot und gibt seinen Pfad aus |
| `session show ID --agent A [--pager]` | zeigt die Rohsitzung an und schreibt nichts |
| `session show --snapshot DATEI [--pager]` | zeigt einen gespeicherten Snapshot an (auch `handoff-v0`) |
| `session export ID --agent A --format markdown\|jsonl [--title T] [--output DATEI]` | Ausgabe auf stdout oder in eine **neue** Datei; kein Archiv |
| `session export --snapshot DATEI --format …` | dasselbe aus einem Snapshot |

```bash
ki-dev session show 0de11ef0-1ad2-48ad-af5c-45fa89e5ecab --agent claude --pager
ki-dev session export --snapshot .local/var/transcripts/261005T22_ryk_0de11ef0.jsonl --format markdown > ryk.md
```

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
`--title` oder aus dem gespeicherten Snapshot; fehlen beide, endet der Aufruf
mit Exit 2. `markdown` enthält denselben Transkriptinhalt (`# Titel`, dann
`## Position Rolle · Zeit` je Beitrag). stdout enthält nur die Daten,
Diagnosen gehen nach stderr. `--output` legt nur eine neue Datei an; eine
vorhandene Datei bleibt unverändert (Exit 1).

Exitcodes: `0` Erfolg; `1` Sitzung oder Snapshot nicht verwendbar (die
Meldung nennt nur Prüfcode, Zeile und Feldpfad); `2` falscher Aufruf
(Anbieter, ID, Titel, Format oder gemischte Auswahl), vor jedem
Dateizugriff.
