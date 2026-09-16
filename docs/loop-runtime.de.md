# Persistenter Bau--Review-Loop

Ein neuer Lauf wird mit einer expliziten JSON-Konfiguration gestartet:

```bash
ki-dev loop --config loop.json --run-id run-42
```

```json
{
  "task": "Den beschriebenen Auftrag umsetzen",
  "sources": ["bd:projekt-42", "docs/vertrag.md"],
  "workdir": "/absoluter/pfad/zum/repository",
  "access_profile": "write",
  "finalization": {
    "target_workdir": "/absoluter/pfad/zum/sauberen-ziel-worktree",
    "target_ref": "refs/heads/main",
    "commit_message": "Geprüfter Abschluss (projekt-42)",
    "data_mode": "file_proposal"
  },
  "build": {
    "executor": "codex",
    "session_id": "build-session",
    "model": "gpt-5.6-terra",
    "effort": "high",
    "timeout_s": 180
  },
  "review": {
    "executor": "claude",
    "session_id": "review-session",
    "model": "sonnet",
    "effort": "high",
    "timeout_s": 180
  },
  "tests": [
    {
      "name": "pytest",
      "argv": [".venv/bin/python", "-m", "pytest", "-q"],
      "timeout_s": 900
    }
  ],
  "limits": {
    "protocol_attempts": 3,
    "worker_attempts": 12,
    "changes_rounds": 5,
    "process_retries": 3
  },
  "projection_limits": {
    "max_file_bytes": 16384,
    "max_file_lines": 200,
    "max_total_bytes": 65536
  }
}
```

`build` und `review` müssen verschiedene vorbereitete Sitzungen benutzen.
Optionale Felder dürfen entfallen; für Grenzen gelten dann die eingebauten
Werte. Unbekannte Felder werden abgewiesen.

Der `workdir` ist der isolierte Bau-/Review-Worktree. `target_workdir` ist ein
zweiter, sauberer Worktree desselben Git-Repositories, der auf `target_ref`
steht. Vor dem Start stehen beide auf demselben Basiscommit. Damit ist der
vollständige Lauf ohne Kopieren von Agentennachrichten startbar; Bau und Review
werden aus der Konfiguration in getrennten Sitzungen fortgesetzt.

Der Lauf liegt unter `.ki-dev/runs/<run-id>/`: SQLite enthält die
LangGraph-Checkpoints, `manifest.json` den unveränderlichen Auftrag samt
Konfiguration, und einzelne JSON-Dateien enthalten unveränderliche
Operations- und Review-Nachweise. Die an den Reviewer übergebene Projektion
bleibt auch nach einem Neustart byte-, zeilen- und gesamtbegrenzt.

Bei `NEEDS_DECISION` und `ESCALATE` hält der Prozess dauerhaft an:

```bash
ki-dev loop resume run-42 --answer "Die gebundene Entscheidung"
```

Eine Eskalation führt nach Resume wieder zum Reviewer und niemals direkt zu
`PASS`. Wenn ein externer Aufruf nachweislich begonnen wurde, aber kein
Ergebnisartefakt existiert, meldet der Lauf `uncertain`. Er wiederholt den
Aufruf nicht automatisch. Damit verspricht der Loop keine unbelegbare
Exactly-once-Ausführung über Agentenprozesse, Git und Beads hinweg.
Nach einem manuellen Abgleich kann das erwartete JSON-Ergebnis der
angezeigten `operation_id` ausdrücklich übernommen werden:

```bash
ki-dev loop resume run-42 --reconcile-result abgeglichen.json
```

Ohne diesen expliziten Abgleich bleibt der Lauf angehalten.

## Verbrauchsschutz

Ein CLI-Aufruf kann viele interne Modellanfragen enthalten.
Deshalb gelten zusaetzlich zu den Maschinenzaehlern folgende
konfigurierbare Standardgrenzen:

| Grenze | Standard | Wirkung |
| --- | ---: | --- |
| `safety_limits.max_agent_calls` | 6 | Bau und Review zusammen, inkl. fehlgeschlagener Aufrufe |
| `safety_limits.max_total_tokens` | 1.000.000 | Input, Cache-Schreiben, Cache-Lesen und Output; Pruefung vor dem naechsten Aufruf |
| `safety_limits.max_claude_cost_usd` | 3 | Summe der von Claude gemeldeten API-Kostenwerte |
| `safety_limits.max_failed_corrections` | 2 | Nach zwei abgelehnten Korrekturen kein weiterer automatischer Bau |
| `build.budget.max_turns` / `review.budget.max_turns` | 12 | Native Claude-Turn-Grenze pro Aufruf |
| `budget.max_budget_usd` je Rolle | 1 | Native Claude-Kostengrenze pro Aufruf |
| `budget.max_context_tokens` je Rolle | 80.000 | Claude-Sitzung vor Resume anhand des letzten realen Requests pruefen |
| `budget.timeout_s` je Rolle | 180 s | Prozesstimeout fuer beide Adapter; der kleinere Wert aus Rollen-Timeout und Budget gilt |

Beispiel fuer eine bewusst kleinere Schranke auf oberster Konfigurationsebene:

```json
"safety_limits": {
  "max_agent_calls": 4,
  "max_total_tokens": 500000,
  "max_claude_cost_usd": 2,
  "max_failed_corrections": 1
}
```

Die Rolle kann ein `budget`-Objekt mit den vier oben genannten Feldern
enthalten. Nicht angegebene Werte erhalten die Standardwerte; wirksame
Rollenbudgets und Laufgrenzen werden beim Start im Manifest gespeichert.
Diese Werte sind Betriebsvorgaben, keine berechneten Abo-Prozentgrenzen.

`calls/` enthaelt unveraenderliche Start- und Ergebnisbelege mit
Verbrauch, Dauer und Fehlergrund. Die Reservierung vor einem Aufruf
wird gesperrt gegen gleichzeitige Reservierungen; ein Neustart setzt
keinen Zaehler zurueck. Die Bilanz zaehlt Cache-Lesetokens mit und
vermeidet bei Codex deren Doppelzaehlung als ungecachten Input.

Ein Agentenfehler, verweigerte Berechtigung, Kontingentabbruch, fehlender
Verbrauchsnachweis oder eine erreichte Grenze fuehrt zu einer
Maschineneskalation `execution_guard`, `paused_interactive` und einem
Interrupt der Art `escalate`. Es folgt kein automatischer Agenten-Retry.
Das gilt auch fuer unbekannte CLI-Fehler; sie gelten nicht ohne Nachweis
als voruebergehend. Fachliche Review-Nachrichten bleiben davon getrennt.

Eine Wiederaufnahme braucht eine ausdrueckliche Antwort. Sie hebt
Verbrauchsgrenzen nicht auf. Ein begonnenes, nicht bilanziertes Ergebnis
bleibt ungeklaert. Beim Abgleich einer solchen `uncertain`-Operation
muss `--reconcile-result` neben dem fachlichen Artefakt auch `usage`
mit `input_tokens`, `output_tokens`, `cache_read_input_tokens` und
`cache_creation_input_tokens` enthalten, bei Claude zusaetzlich
`cost_usd`. Werte muessen aus dem tatsaechlichen Aufruf stammen.
Altläufe ohne Bilanz erhalten keinen automatischen neuen Agentenaufruf.
Ein textuelles „weiter“ ersetzt weder diesen Nachweis noch eine
Neuplanung mit kleinerem Auftrag und vorbereiteter frischer Sitzung.

Die Lauf-Token-/Kostensumme wird an CLI-Schrittgrenzen geprueft und
kann durch den gerade laufenden Aufruf ueberschritten werden. Claude
hat zusaetzlich die nativen Grenzen innerhalb dieses Aufrufs; auch
diese sind keine Reservierung eines exakten Aboanteils. Fuer Codex
werden hier keine nativen Turn-/USD-Grenzen behauptet. Seine
Aufrufe werden zeitlich begrenzt und anschliessend bilanziert.
Andere Laeufe oder manuelle Sitzungen desselben Kontos sind nicht
Teil dieser laufbezogenen Bilanz.

Der konkrete Anlass und die Messmethode stehen in der
[Verbrauchsanalyse zu uar-2-02](ki-dev/uar-2-02-verbrauch.md).

## Gepruefter Abschluss

`PASS` ist noch kein Erfolg. Der Loop bindet es zunächst an den exakten,
zuletzt geprüften Commit sowie dessen Baum-ID. Anschließend erzeugt er einen
kompakten Commit mit dem Laufbasiscommit als Parent und exakt demselben Baum.
Nur wenn Quell- und Zielarbeitsbaum sauber sind, der geprüfte Commit noch
unverändert ist, der Zielbranch noch auf der Laufbasis steht und beide Baum-IDs
identisch sind, führt er im Ziel-Worktree `git merge --ff-only` aus. Erst die
erneute Prüfung des integrierten Commit und Baums ergibt `passed` / `PASSED`.

Alle vier Abschlussoperationen besitzen unveränderliche Artefakte. Nach einem
Prozessabbruch genügt daher:

```bash
ki-dev loop resume run-42
```

Eine bereits nachgewiesene Integration wird dabei nicht wiederholt. Ein
negatives Drift-Gate pausiert; nachdem die äußere Ursache behoben wurde, wird
dieselbe Phase mit einer gebundenen Bedienerantwort erneut geprüft:

```bash
ki-dev loop resume run-42 --answer "Zielstand extern geprüft und korrigiert"
```

## Git- und Beads-/Dolt-Grenze

Ein Git-Worktree isoliert nur Git-Dateistand und Branch, nicht automatisch die
von `bd` verwendete Dolt-Datenbank. Der kleine Go-live-Schnitt unterstützt
deshalb ausschließlich `data_mode: "file_proposal"`: Der Agent darf einen
dateibasierten Änderungsvorschlag erzeugen, aber die Beads-/Dolt-Referenz muss
von der Laufbasis bis über die Integration unverändert bleiben. Direkte
Beads-Schreibwirkungen oder `data_mode: "beads_direct"` werden ausdrücklich
abgewiesen. Sie dürfen erst unterstützt werden, wenn ein eigener isolierter,
versionierter DB-Arbeitsstand samt geprüftem Delta und kontrollierter Übernahme
vorhanden ist. `.beads/issues.jsonl` ist dabei nur Export, nie DB-Wahrheit.
