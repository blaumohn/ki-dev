# CLI-Executor-Adapter

Dieses Dokument beschreibt den ausfuehrbaren Vertrag der beiden
Executor-Adapter (`ClaudeCliAdapter`, `CodexCliAdapter`) und die von
ihnen verwendete CLI-Syntax.

## Gemeinsamer Turn-Vertrag

Modul: `ki_dev.executors.contract`

Ein *Turn* ist genau ein synchroner Prozessaufruf. Das Prozessende
ist die Schrittgrenze. Die Kontrollschleife kennt nur die folgenden
Typen und keinerlei Claude-/Codex-spezifische Argumente.

| Typ | Zweck |
| --- | --- |
| `TurnRequest` | Eingabe: `session_id` (`None`: neue Sitzung anlegen), `message`, `model`, `effort`, optional `budget` und `access` |
| `Access` | `READ` / `WRITE`: Dateizugriff des Turns im Arbeitsverzeichnis, je Adapter in CLI-Rechte uebersetzt; `None` laesst die CLI-Einstellung |
| `TurnBudget` | Interne Claude-Turn-/Kosten-/Kontextgrenzen, gemeinsamer Timeout und `max_usage_delta_percentage_points` (Aufgaben-Delta-Budget des 5h-Kontingents, siehe unten) |
| `Effort` | `LOW` / `MEDIUM` / `HIGH` |
| `TurnResult` | Ausgabe: `status`, `exit_code`, `stdout`, `stderr`, `argv`, `duration_s`, `error`, optional `usage` und `session_id` (bei neuer Sitzung die von der CLI genannte ID) |
| `TurnStatus` | `OK` / `NONZERO_EXIT` / `TIMEOUT` / `START_ERROR` |
| `ContextMeasurement` | Sitzungsbezogener Kontextmesswert: `status` (`ContextStatus`), optional `tokens`, `detail` |
| `ContextStatus` | `MEASURED` / `UNSUPPORTED` / `UNAVAILABLE` |
| `QuotaMeasurement` | Kontobezogener 5h-Kontingentmesswert: `status` (`QuotaStatus`), optional `used_percent`, `resets_at`, `detail` |
| `QuotaStatus` | `MEASURED` / `UNSUPPORTED` / `UNAVAILABLE` -- anders als `ContextStatus` blockieren hier alle drei Nicht-"unter Grenze"-Faelle |
| `Executor` | Protokoll mit `name`, `capabilities`, `send_turn(request) -> TurnResult`, `measure_context(session_id) -> ContextMeasurement` und `measure_quota(session_id) -> QuotaMeasurement` |
| `Measure` | `context` / `quota` / `budget` -- was ein Transport messen kann (`capabilities`) und ein Executor deklariert (`measures`) |
| `ExecutorSpec` | Deklarierter Executor: `name`, `transport`, `measures` |

Ein Adapter liefert mit `measure_context`/`measure_quota` nur den
Messwert. Freigabe, Halt und Persistenz einer erreichten Kontext- oder
Kontingentgrenze entscheidet ausschliesslich die Orchestrierung
(`flow_ops.implement.runtime._context_guard`/`_quota_guard`, siehe
[ausfuehrer.de.md](ausfuehrer.de.md#kontextvorpruefung) und
[ausfuehrer.de.md](ausfuehrer.de.md#fuenfstundenkontingent-vorpruefung)),
nie der Adapter selbst und nie eine Selbsteinschaetzung des Agenten.

`TurnStatus` ist disjunkt: Erfolg, Nicht-null-Exit, Timeout und
Prozessstartfehler sind eindeutig unterscheidbar. Es gibt keine
stillen Fallbacks; jeder Nicht-Erfolg traegt eine `error`-Meldung.

### Executor-unabhaengiger Einstieg

Modul: `ki_dev.adapter.executors.dispatch`

Die Kontrollschleife waehlt keine Adapterklasse aus. Sie nennt nur
den Transportnamen und die vier Vertragswerte:

```
send_turn(transport, *, session, message, model, effort) -> TurnResult
```

* `transport` ist `"claude-cli"` oder `"codex-cli"` (`cli_transports()`).
* `build_executor(transport, **adapter_kwargs)` liefert bei Bedarf den
  Adapter allein.
* Ein unbekannter Transport bricht mit `ValueError` ab; es gibt
  keinen stillen Standard-Transport.

Welcher Executor-Name (`claude`, `codex`, `manual`, `inbox`, `mock`)
welchen Transport nutzt und welche Messungen der Ausfuehrer verlangt,
steht als Daten in `src/ki_dev/adapter/executors.toml`
(`adapter/registry.py`, siehe
[ausfuehrer.de.md](ausfuehrer.de.md#executoren)).

Jedes executor-spezifische CLI-Argument bleibt vollstaendig im
jeweiligen Adapter.

### Gemeinsamer Prozesslauf

Modul: `ki_dev.executors.process` (`run_cli_turn`)

* Der externe Prozess wird ueber **Plumbum** gestartet
  (`plumbum.local[...]`), gemaess vorgesehenem Python-Werkzeugsatz aus
  Quellen-Bead ki-dev-ablauf-9p4a.
* `message` wird der CLI ueber **stdin** uebergeben (Plumbum
  `command << message`), nicht als Argument – keine Escaping-/
  Laengenprobleme, saubere `argv`.
* Der Prozess erbt die Umgebung des Aufrufers samt der bereits
  eingerichteten CLI-Anmeldung. Es findet keine
  API-Schluesselverwaltung und kein Login statt.
* `plumbum.CommandNotFound` und `OSError` (nicht ausfuehrbare CLI)
  -> `START_ERROR`.
* `plumbum.commands.processes.ProcessTimedOut` -> `TIMEOUT`. Der
  Prozess wird beendet; `stdout`/`stderr` bleiben leer (Plumbum gibt
  bei Timeout keine Teilausgabe heraus).
* Exitstatus `0` -> `OK`, sonst -> `NONZERO_EXIT` (`run(retcode=None)`
  laesst jeden Exitcode zu, statt eine Ausnahme zu werfen).

Der Standard-Timeout ist `DEFAULT_TIMEOUT_S = 900` Sekunden und pro
Adapterinstanz ueberschreibbar.
`ki-dev -f implement` uebergibt immer ein `TurnBudget`; dessen Standardtimeout
betraegt 180 Sekunden und begrenzt den Adaptertimeout zusaetzlich.
Alle Zeit- und Kostengrenzen muessen positiv und endlich sein.

### Versionsprobe teilt sich die Zeitgrenze mit dem Turn

Modul: `ki_dev.executors.base` (`CliAdapter.send_metered_turn`)

Ein budgetierter Turn (`TurnRequest.budget` gesetzt) fuehrt vor dem
eigentlichen Prozessaufruf `<cli> --version` aus, um die tatsaechlich
ausgefuehrte CLI-Version nachzuweisen (siehe `cli_version_pin`
unten) statt sie aus dem gepinnten Bezugsstand zu behaupten. Probe und
Turn teilen sich EINE gemeinsame Zeitgrenze (`budget.timeout_s`, siehe
oben) statt sie zu verdoppeln:

* Die Probe erhaelt hoechstens `VERSION_PROBE_TIMEOUT_S = 10` Sekunden
  (eine lokale Versionsausgabe braucht keine Modell-/
  Netzwerklaufzeit).
* Der Turn erhaelt danach nur noch die verbleibende Restzeit der
  Rollen-Frist, nicht erneut die volle Frist.
* Ist die Frist bereits durch die Probe aufgebraucht, startet kein
  Turn-Prozess mehr; das Ergebnis ist `TurnStatus.TIMEOUT` ohne
  `claude_result()`/`codex_result()`-Nachbearbeitung (die ist fuer ein
  tatsaechliches Prozessergebnis gebaut).

Meldet die Probe eine andere Version als `cli_version_pin` (oder keine
lesbare), startet ebenfalls kein Turn: das Ergebnis ist
`TurnStatus.START_ERROR` mit „`codex 0.170.0 ist nicht geprüft, erwartet
0.164.0`“. Der Verbrauch einer ungeprüften Version waere nur ein
`PARTIAL`-Beleg, der jede weitere Reservierung des Laufs sperrt
(Sicherheitsvertrag: ein unverifizierter Anbieterstand sperrt reale
Ausfuehrung). Ein nicht gestarteter Aufruf hat nachweislich nichts
verbraucht (`started: false` im Aufrufergebnis) und sperrt die Bilanz
nicht: nach `make setup-agents` (geprueften Stand nach `.venv/bin`)
setzt `resume --answer "…"` den Lauf fort.

## Antwortschema

`TurnRequest.output_schema` lässt die CLI die Form der Antwort erzwingen;
`None` lässt sie frei. Claude erhält `--json-schema <JSON>`, Codex
`--output-schema <Datei>` (Datei nur für diesen Aufruf, außerhalb des
Worktrees). Beides gilt auch beim Fortsetzen einer Sitzung.

Beobachtet mit Claude Code 2.1.316 und codex 0.166.0 (Fixtures:
`tests/golden/executors/`):

* Oberstes `allOf`/`anyOf`/`oneOf`/`enum`/`not` lehnen beide mit HTTP 400
  ab. Codex verlangt zudem jedes Feld in `required`. `cli_schema` entfernt
  deshalb die `if`/`then`-Regeln; `pattern` und `minLength` nehmen beide an.
* Claude liefert die Antwort über ein eigenes Werkzeug
  (`StructuredOutput`) und legt sie in `structured_output` des
  `result`-Ereignisses ab; `claude_result` bevorzugt dieses Feld. Es läuft
  auch mit `--tools Read,Grep,Glob`.
* Codex liefert sie als letzte `agent_message`.

Ein abgelehntes Schema ist ein gewöhnlicher Turn-Fehler, kein leerer
Erfolg. ki-dev prüft die Antwort immer selbst (zweite Sicherung); genau ein
umschließender Codeblock bleibt für freie Antworten erlaubt
(`unwrap_json_fence`: Worker, Mensch als Bote).

## ClaudeCliAdapter

Verwendete CLI: **Claude Code CLI** (`claude`), nachweisbar per
`claude --version`.

* **Versionsstand:** zentral in `src/ki_dev/tool-versions.json`;
  `tests/executors/test_cli_versions.py` vergleicht die lokale CLI damit.

Gebildeter Aufruf:

```
claude --print --output-format text \
       --model <model> \
       --resume <session_id> | --session-id <neue UUID> \
       --effort <low|medium|high> \
       [--tools Read,Grep,Glob | --permission-mode acceptEdits]
# message -> stdin
```

* `--print` – nicht-interaktiver Einzeldurchlauf, Antwort nach
  stdout.
* `--resume <session_id>` – setzt eine bestehende Sitzung fort.
* `--session-id <UUID>` – ohne `session_id` legt der Turn eine neue
  Sitzung an; die UUID waehlt der Adapter. Die ID im Ergebnis
  (`TurnResult.session_id`) stammt aus dem `result`-Ereignis von
  `stream-json`; fehlt sie nach einem erfolgreichen Turn, ist das ein
  Fehler. Eine neue Sitzung braucht deshalb ein `TurnBudget`.
* `access` `READ` → `--tools Read,Grep,Glob`: nur Lesewerkzeuge, also
  keine Rueckfrage, die `--print` als verweigerte Berechtigung meldet.
  `WRITE` → `--permission-mode acceptEdits`: Dateiaenderungen ohne
  Rueckfrage; Shell-Befehle brauchen weiterhin eine Freigabe in den
  Claude-Einstellungen.
* `--model <model>` – Modellwahl unveraendert aus dem Vertrag.
* `--effort <stufe>` – nativer Effort-Schalter der Claude-CLI
  (gueltige Werte in 2.1.272: `low`, `medium`, `high`, `xhigh`,
  `max`). Die drei Vertragsstufen werden unveraendert durchgereicht.

Mit `TurnBudget` (immer in `ki-dev -f implement`) verwendet der Adapter stattdessen
`--output-format stream-json --verbose --max-turns 12
--max-budget-usd 1.0`, mit den jeweils konfigurierten Grenzwerten.
Die Antwort steht im `result`-Ereignis, der 5h-Wert im
`rate_limit_event` (siehe `measure_quota`).

`measure_context(session_id)` liest die lokale vorbereitete Sitzung
unter `~/.claude/projects/*/<session_id>.jsonl` und liefert den
zuletzt bekannten Kontext als `ContextMeasurement`. Synthetische
Fehler mit Nullusage verschleiern dabei nicht den letzten echten
Kontext. Fehlende, mehrdeutige oder unlesbare Sitzungsdaten ergeben
`UNAVAILABLE` statt einer Ausnahme oder eines erfundenen Nullwerts;
ob das den naechsten Aufruf verhindert, entscheidet ausschliesslich
die Orchestrierung (siehe oben), nicht dieser Adapter. Das Lesen
selbst startet keinen Prozess und ist verbrauchsfrei.

`measure_quota(session_id)` liest den Wert, den der vorige Turn
abgelegt hat. Claude liefert den 5h-Anteil verbrauchsfrei nur mit
einer Antwort: `stream-json --verbose` enthaelt ein `rate_limit_event`
mit `rate_limit_info.unifiedWindows.five_hour.utilization` (Anteil
0..1) und `resetsAt` (verifiziert mit 2.1.272). Der Adapter speichert
ihn nach jedem Turn unter `~/.cache/ki-dev/claude-quota/<session_id>.json`.
Vor dem ersten Turn und nach einem Fensterwechsel gilt `PENDING`: Der
Aufruf laeuft ungemessen, ab dem naechsten greifen Reserve und
Delta-Budget. Ein Turn ohne `rate_limit_event` (Abbruch, Fehler) laesst den letzten Wert stehen
(siehe
[ausfuehrer.de.md](ausfuehrer.de.md#fuenfstundenkontingent-vorpruefung)).

Das JSON-Resultat liefert Antworttext und `usage` getrennt. Auch bei
Exitcode 0 gelten `is_error`, ein Fehler-`subtype` oder
`permission_denials` als Nicht-Erfolg. Fehlende Pflichtdaten werden
nicht durch geschaetzte Nullkosten ersetzt. Native Flags und
Ergebnisfelder sind in der
[Claude-CLI-Referenz](https://code.claude.com/docs/en/cli-reference)
und der [Verbrauchsdokumentation](https://code.claude.com/docs/en/agent-sdk/cost-tracking)
beschrieben. Die Flags sind auch im installierten Bezugsstand vorhanden.

## CodexCliAdapter

Verwendete CLI: **OpenAI Codex CLI** (`codex`), nachweisbar per
`codex --version`.

* **Versionsstand:** zentral in `src/ki_dev/tool-versions.json`;
  `tests/executors/test_cli_versions.py` vergleicht die lokale CLI damit.

Gebildeter Aufruf:

```
codex exec [resume <session_id>] \
      --model <model> \
      -c model_reasoning_effort=<low|medium|high> \
      [-c sandbox_mode="read-only|workspace-write"] \
      -
# message -> stdin
```

* `exec resume <session_id>` – nicht-interaktive Fortsetzung einer
  bestehenden Sitzung. Ohne `session_id` legt `codex exec` eine neue an;
  ihre ID kommt aus dem Ereignis `thread.started` der `--json`-Ausgabe
  (eine neue Sitzung braucht deshalb ein `TurnBudget`).
* `-c sandbox_mode=…` – `access` `READ` → `read-only`, `WRITE` →
  `workspace-write`; ohne `access` gilt die Codex-Einstellung (fuer
  `codex exec` standardmaessig lesend).
* `--model <model>` – Modellwahl unveraendert aus dem Vertrag.
* `-c model_reasoning_effort=<stufe>` – direkte Uebersetzung von
  `effort` in den Codex-Konfigurationsschluessel.
* abschliessendes `-` – Prompt wird von stdin gelesen.

Mit `TurnBudget` aktiviert der Adapter `--json`. Er extrahiert die
letzte abgeschlossene Agentenantwort und den Verbrauch aus
`turn.completed`. Fehlerereignisse oder fehlende Verbrauchswerte
sind kein Erfolg. `cached_input_tokens` ist eine Teilmenge von
`input_tokens`; in der gemeinsamen Bilanz wird dieser Anteil genau
einmal gezaehlt. Die Claude-spezifischen Turn-/Kosten-/Kontextgrenzen
werden nicht als unterstuetzte Codex-Funktionen ausgegeben.
`measure_context` liefert deshalb unveraendert den `UNSUPPORTED`-
Standard aus `CliAdapter`: Codex hat keine mit Claudes
Sitzungsprotokoll vergleichbare lokale Ablage, aus der sich ein
Kontextmesswert unabhaengig belegen liesse. `codex-cli` nennt
`context` deshalb nicht in `capabilities`, der Executor `codex`
deklariert es nicht, und der Kontextwaechter gilt fuer ihn nicht
(siehe [ausfuehrer.de.md](ausfuehrer.de.md#kontextvorpruefung)).

`measure_quota` liest dagegen verbrauchsfrei die lokale Rollout-Ablage
unter `~/.codex/sessions/JJJJ/MM/TT/rollout-*-<session_id>.jsonl`
(`codex_quota.codex_quota`) -- nachgewiesen fuer `codex exec`
(Sitzungsherkunft `codex_exec` im `session_meta`-Ereignis) ebenso wie
fuer interaktive Sitzungen. Codex schreibt dort periodisch ein
`token_count`-Ereignis mit einer `rate_limits`-Momentaufnahme
(`primary`/`secondary`, je `used_percent`/`window_minutes`/
`resets_at`); das 5h-Fenster ist das mit `window_minutes == 300`, nicht
positional `primary`. Gezaehlt wird nur der Kontingent-Topf des Kontos
(`rate_limits.limit_id` `codex`, aeltere Versionen ohne `limit_id`);
andere Toepfe wie `premium` (ohne Fenster) oder modellgebundene mit
eigenem 5h-Fenster werden uebergangen, ebenso Zeilen nur mit
Wochenfenster. Das Kontingent ist kontoweit, nicht
sitzungsgebunden: gemessen wird das zeitlich juengste
`token_count`-Ereignis ueber alle lokalen Rollouts, nicht nur die der
uebergebenen `session_id` -- deren eigene Rollout-Datei dient nur als
Gueltigkeitspruefung (genau eine bekannte Sitzung), nicht als
Messquelle, da eine laenger inaktive eigene Sitzung sonst einen zu
niedrigen, veralteten Wert liefern wuerde. Die Suche (`codex_quota.
_freshest_account_window`) liest jede Rollout-Datei vollstaendig, ohne
Fruehabbruch nach Datei-Aenderungszeit: eine Beziehung zwischen der
Aenderungszeit einer Datei und dem in ihrem Inhalt stehenden
Ereignis-Zeitstempel ist technisch nicht garantiert (Kopien,
Wiederherstellung, verzoegertes Schreiben) und traegt deshalb keine
Suchbegrenzung. Der Vergleich laeuft -- zwischen Dateien und innerhalb
einer Datei -- ueber geparste Zeitwerte, nicht ueber die Zeitstempel-
Strings (unterschiedliche Nachkommastellen-Laenge sortiert als Text
falsch) und nicht ueber die physische Zeilenreihenfolge (eine
chronologisch sortierte Zeilenfolge ist technisch nicht garantiert).

Ein Messwert gilt nur als aktuell, wenn sein Fenster nicht abgelaufen
und er juenger als `MAX_MEASUREMENT_AGE_S` (Standard 1800 s) ist -- ein
noch nicht abgelaufenes Fenster allein beweist keine Aktualitaet. Fehlt
ein aktueller Wert, misst wie bei claude-cli erst die Antwort: `PENDING`
fuer eine neue Sitzung (auch ohne jeden Messwert) und nach einem
abgelaufenen oder zu alten Wert; der Aufruf laeuft ungemessen, danach
steht der Wert in seiner eigenen Rollout-Datei. Hat die genannte Sitzung
seit dem letzten Messwert schon ohne Messwert geantwortet oder gibt es
fuer eine genannte Sitzung keinen, liefert Codex fuer dieses Konto keinen
Nachweis: `UNAVAILABLE` statt einer Folge ungemessener Aufrufe. Ein
Ereignis-Zeitstempel merklich in der Zukunft (jenseits
`CLOCK_SKEW_TOLERANCE_S`) gilt als unplausibel (`UNAVAILABLE`). Die
Kontozuordnung der durchsuchten Ablage (`CODEX_HOME` bildet
durchgehend ein Konto ab) ist eine dokumentierte, technisch nicht
pruefbare Betriebsvoraussetzung; weder `session_meta` noch
`rate_limits` tragen ein Kontomerkmal, die Altersschwelle mindert das
Risiko zusaetzlich. Anders als bei `measure_context` blockiert ein
fehlender Nachweis (`UNAVAILABLE`) hier den naechsten Aufruf
(siehe
[ausfuehrer.de.md](ausfuehrer.de.md#fuenfstundenkontingent-vorpruefung)).

## Sitzungstranskripte (Adaptergrenze)

`adapter/executors/transcript.py` liest die lokale Sitzung eines Anbieters als
neutrales `SessionTranscript` (`agent`, `session_id`, `source_digest`,
`parser_version`, optional belegte `started_at`/`last_activity_at`,
Nachrichten mit `position`, `ordinal`, `role`, `text`, `source_line`,
optionalem `timestamp`, begrenzte Diagnosezaehler). `position` ist die
normalisierte Reihenfolge, `ordinal` die Herkunftsnummer (Claude:
`None`). `validate_transcript` prueft den Typ als Daten im Speicher
gegen einen gemeinsamen JSON-Schema-Vertrag; `require_started_at`
laesst datumsbasierte Ablage ohne belegten Start sichtbar scheitern.
Die Faehigkeit ist unabhaengig von `available_executors()`: sie haengt
nur an `read_session_transcript(agent, session_id)` und einer eigenen
Dispatch-Tabelle. Unterstuetzt sind `codex` und `claude`.

Alle Codex-Einzelheiten liegen in `codex_sessions.py` (ID-Regeln,
Verzeichnis, Dateisuche) und `codex_transcript.py` (Filter, Pruefungen,
Hash). Die Suche `find_session_rollout` teilt sich `codex_quota`; die
kontoweite Quota-Semantik (`_freshest_account_window`) liegt dort.

- **Verzeichnis:** `KI_DEV_CODEX_SESSIONS_DIR` (ausdruecklicher
  Sitzungsordner), sonst `CODEX_HOME/sessions`, sonst
  `~/.codex/sessions`. Ein gesetzter, aber leerer Wert ist ein Fehler.
  Die Umgebung wird nur in `read_codex_session` gelesen.
- **ID:** nur `[A-Za-z0-9][A-Za-z0-9_-]*`; keine Pfadseparatoren, keine
  Glob-Metazeichen. Genau ein Treffer, kein neuester-Treffer-Fallback.
- **Eingangsvertrag:** Benutzer-`UserMessage` und Assistenten-
  `final_answer`. Die strenge cg1-Annahme (strikter Wechsel, gleiche
  Anzahl) ist abgeloest: T1 (nur eine Rolle), T2 (ungleiche Anzahl) und
  T4 (Rollenbrueche) sind nur Zaehler in `diagnostics`. Fehler bleiben
  T0 (keine Nachricht), T3 (endliches eindeutiges `ordinal`), T5
  (Beinahe-Treffer), T6 (leere Texte), T7 (`turn_id`-Paare bei sauberem
  Wechsel), T8 (ungueltiger Zeitstempel, widerspruechlicher Start) und
  J1 (ungueltiges JSON, auch als Teilzeile am Ende). Abweichungen sind
  Plausibilitaets-/Formatfehler, kein bewiesener CLI-Versionswechsel;
  es gibt keine stille Reparatur.
- **Start:** `started_at` nur aus `session_meta` mit passender
  `payload.id`; nie aus Dateiname, mtime oder Exportdatum.
- **Diagnosen:** nur Pruefcode, Zeile, Feldpfad und Zaehler, hoechstens
  10 Faelle je Pruefung samt Zahl der ausgelassenen; nie
  Gespraechsausschnitte oder Rohereignisse.
- **Ein Lesevorgang:** Die Datei wird einmal als Bytes gelesen; Hash und
  Extraktion beziehen sich auf genau diesen Stand.

Claude-Einzelheiten liegen in `claude_sessions.py` (ID-Regeln,
Projektwurzel, Dateisuche; geteilt mit `claude_context_tokens`) und
`claude_transcript.py` (fachlich aus `mdman-ai-session` uebernommen).

Der Transkriptadapter liest und extrahiert den Dialog;
`claude_transcript_schema.py` buendelt die Datenvertraege,
`claude_transcript_content.py` die Inhaltsklassifikation.

- **Verzeichnis:** `KI_DEV_CLAUDE_SESSIONS_DIR` (ausdrueckliche
  Projektwurzel), sonst `~/.claude/projects`; gesucht wird
  `PROJEKT/SESSION_ID.jsonl`. Leerer Wert ist ein Fehler. Der Executor
  (`measure_context`) nutzt weiter fest `~/.claude/projects`.
- **Filter:** menschliche Eingaben (`origin.kind=human`,
  `promptSource` `typed`/`queued`) und `end_turn`-Text. Assistant-Text
  mit `stop_reason=tool_use` oder explizitem `stop_reason=null`
  (laufende/unterbrochene Antwort) wird als Zwischenstand gezaehlt
  und ausgelassen; die Eingabe bleibt ohne `end_turn` offen.
  Aufgabenmeldungen nur bei belegter technischer Herkunft ausgelassen
  und gezaehlt,
  Slash-Befehlszeilen und Verdichtungszusammenfassungen (beide
  Kennzeichen `isCompactSummary`/`isVisibleInTranscriptOnly`) nur ohne
  jede Herkunftsangabe; menschliche Zitate
  (auch mit fuehrendem Tag) bleiben. Jede `sessionId` muss der
  angeforderten Sitzung entsprechen. Unbekannte Herkunft, ungueltiges
  JSON, Schema- und Kettenfehler sowie leere Transkripte sind Fehler.
  Wiederholte Rollen und offene Eingaben sind gueltig und gezaehlt.
- **Zeit:** `timestamp` ist optional; fehlt er, bleibt er fehlend
  (gezaehlt als `records_without_timestamp`), ein ungueltiger Wert ist
  ein Fehler. `started_at` ist der frueheste, `last_activity_at` der
  spaeteste vorhandene Zeitstempel der Sitzungsbeitraege, sonst `None`.

## Effort im Turn-Vertrag

Beide CLIs kennen einen eigenen Effort-Mechanismus: Codex ueber
`model_reasoning_effort`, Claude ueber `--effort`. Der Adapter reicht
die Vertragsstufe jeweils direkt an den nativen Schalter weiter. Es
gibt keine erfundene Ersatzuebersetzung und keinen stillen Verlust
der Angabe.

## Nicht abgedeckt

Controller-/Worker-Zustandsmaschine, Schleifenverkabelung, direkte
OpenAI-/Anthropic-APIs, API-Schluesselverwaltung, Login bzw.
Sitzungserzeugung, PTY-/Terminalfernsteuerung und die Pages-PM-
Integration sind nicht Teil dieser Adapter.
