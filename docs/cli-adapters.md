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
| `TurnRequest` | Eingabe: `session_id`, `message`, `model`, `effort`, optional `budget` |
| `TurnBudget` | Interne Claude-Turn-/Kosten-/Kontextgrenzen, gemeinsamer Timeout und `max_usage_delta_percentage_points` (Aufgaben-Delta-Budget des 5h-Kontingents, siehe unten) |
| `Effort` | `LOW` / `MEDIUM` / `HIGH` |
| `TurnResult` | Ausgabe: `status`, `exit_code`, `stdout`, `stderr`, `argv`, `duration_s`, `error`, optional `usage` |
| `TurnStatus` | `OK` / `NONZERO_EXIT` / `TIMEOUT` / `START_ERROR` |
| `ContextMeasurement` | Sitzungsbezogener Kontextmesswert: `status` (`ContextStatus`), optional `tokens`, `detail` |
| `ContextStatus` | `MEASURED` / `UNSUPPORTED` / `UNAVAILABLE` |
| `QuotaMeasurement` | Kontobezogener 5h-Kontingentmesswert: `status` (`QuotaStatus`), optional `used_percent`, `resets_at`, `detail` |
| `QuotaStatus` | `MEASURED` / `UNSUPPORTED` / `UNAVAILABLE` -- anders als `ContextStatus` blockieren hier alle drei Nicht-"unter Grenze"-Faelle |
| `Executor` | Protokoll mit `name`, `send_turn(request) -> TurnResult`, `measure_context(session_id) -> ContextMeasurement` und `measure_quota(session_id) -> QuotaMeasurement` |

Ein Adapter liefert mit `measure_context`/`measure_quota` nur den
Messwert. Freigabe, Halt und Persistenz einer erreichten Kontext- oder
Kontingentgrenze entscheidet ausschliesslich die Orchestrierung
(`loop_runtime._context_guard`/`_quota_guard`, siehe
[loop-runtime.de.md](loop-runtime.de.md#kontextvorpruefung) und
[loop-runtime.de.md](loop-runtime.de.md#fuenfstundenkontingent-vorpruefung)),
nie der Adapter selbst und nie eine Selbsteinschaetzung des Agenten.

`TurnStatus` ist disjunkt: Erfolg, Nicht-null-Exit, Timeout und
Prozessstartfehler sind eindeutig unterscheidbar. Es gibt keine
stillen Fallbacks; jeder Nicht-Erfolg traegt eine `error`-Meldung.

### Executor-unabhaengiger Einstieg

Modul: `ki_dev.executors.dispatch`

Die Kontrollschleife waehlt keine Adapterklasse aus. Sie nennt nur
den Executor-Namen und die vier Vertragswerte:

```
send_turn(executor, *, session, message, model, effort) -> TurnResult
```

* `executor` ist `"claude"` oder `"codex"` (`available_executors()`).
* `build_executor(executor, **adapter_kwargs)` liefert bei Bedarf den
  Adapter allein.
* Ein unbekannter Executor-Name bricht mit `ValueError` ab; es gibt
  keinen stillen Standard-Executor.

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
`ki-dev loop` uebergibt immer ein `TurnBudget`; dessen Standardtimeout
betraegt 180 Sekunden und begrenzt den Adaptertimeout zusaetzlich.
Alle Zeit- und Kostengrenzen muessen positiv und endlich sein.

### Versionsprobe teilt sich die Zeitgrenze mit dem Turn

Modul: `ki_dev.executors.base` (`CliAdapter.send_metered_turn`)

Ein budgetierter Turn (`TurnRequest.budget` gesetzt) fuehrt vor dem
eigentlichen Prozessaufruf `<cli> --version` aus, um die tatsaechlich
ausgefuehrte CLI-Version nachzuweisen (siehe `verified_cli_version`
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

## ClaudeCliAdapter

Verwendete CLI: **Claude Code CLI** (`claude`), nachweisbar per
`claude --version`.

* **Verifizierter Bezugsstand:** Claude Code **2.1.272**
  (`claude_cli.VERIFIED_CLI_VERSION`, getestet in
  `tests/executors/test_cli_versions.py`).

Gebildeter Aufruf:

```
claude --print --output-format text \
       --model <model> \
       --resume <session_id> \
       --effort <low|medium|high>
# message -> stdin
```

* `--print` – nicht-interaktiver Einzeldurchlauf, Antwort nach
  stdout.
* `--resume <session_id>` – setzt die vorbereitete Sitzung fort.
* `--model <model>` – Modellwahl unveraendert aus dem Vertrag.
* `--effort <stufe>` – nativer Effort-Schalter der Claude-CLI
  (gueltige Werte in 2.1.272: `low`, `medium`, `high`, `xhigh`,
  `max`). Die drei Vertragsstufen werden unveraendert durchgereicht.

Mit `TurnBudget` (immer im Loop) verwendet der Adapter stattdessen
`--output-format json --max-turns 12 --max-budget-usd 1.0`, mit den
jeweils konfigurierten Grenzwerten.

`measure_context(session_id)` liest die lokale vorbereitete Sitzung
unter `~/.claude/projects/*/<session_id>.jsonl` und liefert den
zuletzt bekannten Kontext als `ContextMeasurement`. Synthetische
Fehler mit Nullusage verschleiern dabei nicht den letzten echten
Kontext. Fehlende, mehrdeutige oder unlesbare Sitzungsdaten ergeben
`UNAVAILABLE` statt einer Ausnahme oder eines erfundenen Nullwerts;
ob das den naechsten Aufruf verhindert, entscheidet ausschliesslich
die Orchestrierung (siehe oben), nicht dieser Adapter. Das Lesen
selbst startet keinen Prozess und ist verbrauchsfrei.

`measure_quota(session_id)` liefert unveraendert den `UNSUPPORTED`-
Standard aus `CliAdapter`: Claude Code meldet den 5h-Kontingentanteil
(`rate_limits.five_hour.used_percentage`) nachweislich nur an ein
interaktives `statusLine`-Skript und `/usage` (Claude-Code-Changelog
2.1.80); die lokale Sitzungsablage traegt das Feld auch bei Erfolg
nicht, sondern nur reaktiv im Fehlerfall (`quotaLimits` bei HTTP 429,
also erst nachdem das Kontingent bereits erreicht ist). Ohne
verifizierten, verbrauchsfreien, nicht-interaktiven Messweg bleibt
dieser Adapter bei `UNSUPPORTED`, statt eine ungeprüfte Messquelle zu
erfinden. Anders als bei `measure_context` blockiert das hier jeden
weiteren Aufruf (siehe
[loop-runtime.de.md](loop-runtime.de.md#fuenfstundenkontingent-vorpruefung)).

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

* **Verifizierter Bezugsstand:** Codex CLI **0.154.0**
  (`codex_cli.VERIFIED_CLI_VERSION`, getestet in
  `tests/executors/test_cli_versions.py`).

Gebildeter Aufruf:

```
codex exec resume <session_id> \
      --model <model> \
      -c model_reasoning_effort=<low|medium|high> \
      -
# message -> stdin
```

* `exec resume <session_id>` – nicht-interaktive Fortsetzung der
  vorbereiteten Sitzung.
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
Kontextmesswert unabhaengig belegen liesse. `UNSUPPORTED` ist ein
bekannter, dokumentierter Adaptergrenzfall und blockiert deshalb
keinen Aufruf (siehe
[loop-runtime.de.md](loop-runtime.de.md#kontextvorpruefung)) --
anders als `UNAVAILABLE`, das eine vorgesehene, aber fehlgeschlagene
Messung waere.

`measure_quota` liest dagegen verbrauchsfrei die lokale Rollout-Ablage
unter `~/.codex/sessions/JJJJ/MM/TT/rollout-*-<session_id>.jsonl`
(`metering.codex_quota`) -- nachgewiesen fuer `codex exec`
(Sitzungsherkunft `codex_exec` im `session_meta`-Ereignis) ebenso wie
fuer interaktive Sitzungen. Codex schreibt dort periodisch ein
`token_count`-Ereignis mit einer `rate_limits`-Momentaufnahme
(`primary`/`secondary`, je `used_percent`/`window_minutes`/
`resets_at`); das 5h-Fenster ist das mit `window_minutes == 300`, nicht
positional `primary`. Das Kontingent ist kontoweit, nicht
sitzungsgebunden: gemessen wird das zeitlich juengste
`token_count`-Ereignis ueber alle lokalen Rollouts, nicht nur die der
uebergebenen `session_id` -- deren eigene Rollout-Datei dient nur als
Gueltigkeitspruefung (genau eine bekannte Sitzung), nicht als
Messquelle, da eine laenger inaktive eigene Sitzung sonst einen zu
niedrigen, veralteten Wert liefern wuerde. Die Suche (`metering.
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

Drei weitere Bedingungen, bevor ein Messwert als Nachweis gilt: ein
`resets_at` in der Vergangenheit ergibt `UNAVAILABLE` statt eines
veralteten Werts als `0`; ein Ereignis-Zeitstempel merklich in der
Zukunft (jenseits `CLOCK_SKEW_TOLERANCE_S`) gilt als unplausibel,
nicht als "besonders frisch"; und der Messwert muss juenger als
`MAX_MEASUREMENT_AGE_S` (Standard 1800 s) sein -- ein noch nicht
abgelaufenes Fenster allein beweist keine Aktualitaet. Die
Kontozuordnung der durchsuchten Ablage (`CODEX_HOME` bildet
durchgehend ein Konto ab) ist eine dokumentierte, technisch nicht
pruefbare Betriebsvoraussetzung; weder `session_meta` noch
`rate_limits` tragen ein Kontomerkmal, die Altersschwelle mindert das
Risiko zusaetzlich. Anders als bei `measure_context` blockiert ein
fehlender, veralteter oder zu alter Nachweis hier den naechsten Aufruf
(siehe
[loop-runtime.de.md](loop-runtime.de.md#fuenfstundenkontingent-vorpruefung)).

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
