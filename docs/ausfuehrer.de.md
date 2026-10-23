# Ausführer: `ki-dev -f implement`

Der Ausführer fährt einen deklarativen Ablauf
([`src/ki_dev/flow/implement.toml`](../src/ki_dev/flow/implement.toml)) bis zum
nächsten Halt. Er liest die formale Antwort eines Adapters, macht daraus
ein Ereignis, wählt mit den Wächtern des Ablaufs die Kante, führt deren
Aktion aus und gibt die nächste Eingabe aus. Eine eigene Topologie hat er
nicht: Welche Operation in welchem Zustand läuft (`operation`), welche
Korrekturrunde noch erlaubt ist und wohin ein Schutzhalt führt, steht im
Ablauf. Die Kante wählt python-statemachine aus `[statechart]` der
Ablaufdatei. Der Lauf ist eine parallele Statechart im Gerüst
(`src/ki_dev/runner/run.toml`): der Ablauf ist darin eine Region neben
`operation` (offene Operation) und `halt` (fährt, pausiert, wartet,
beendet); eine Eskalation, ein wartender Zustand und das Ende des
Ablaufs halten den Lauf über die Bibliothek an, nicht über Code. Nach jedem
Schritt ersetzt der Ausführer den Datensatz des Laufs atomar; ein Halt
beendet den Prozess, `resume` liest den Datensatz.

Ein neuer Lauf nimmt den Auftrag aus einem Bead und Rollen, Prüfungen
und Grenzen aus einem Profil:

```bash
ki-dev -f implement proj-42                      # Profil .ki-dev/profiles/default.toml
ki-dev -f implement proj-42 --profile lokal      # .ki-dev/profiles/lokal.toml
ki-dev -f implement proj-42 --adapter review=manual   # Review von Hand
```

`-f NAME` sucht wie `make -f`: `./NAME.toml`, dann die Verzeichnisse aus
`KI_DEV_FLOW_PATH`, dann das mitgelieferte Paket (`ki_dev/flow/`); die
gefundene Datei steht auf stderr. Die Ablaufdatei nennt in `ops` das
Modul, das ihre Befehle umsetzt (`ki_dev.flow_ops.implement`: `start`,
`resume`, `status`, `history`). Der Ausführer bindet bisher nur das mitgelieferte
`implement.toml`; eine abweichende Datei wird abgewiesen.

Aus dem Bead (Pflichtfelder wie bei `ki-dev -f implement_review step BEAD implement`):
Titel, Beschreibung, Design und die Übersicht der Eltern-Epics werden
`task`, `acceptance_criteria` (nummeriert `1.`, `2.` …) werden `AC1`,
`AC2` …, `sources` ist `bd:BEAD` plus `metadata.handoff.source_refs`.

Das Profil (TOML) enthält alles andere; Auftragsfelder darin sind ein
Fehler:

```toml
workdir = "/absoluter/pfad/zum/repository"
access_profile = "write"

[env]
PYTHONPATH = "/absoluter/pfad/zum/repository/src"

[finalization]
target_workdir = "/absoluter/pfad/zum/sauberen-ziel-worktree"
target_ref = "refs/heads/main"
commit_message = "Geprüfter Abschluss (projekt-42)"
data_mode = "file_proposal"

[worker]
executor = "codex"
session_id = "build-session"
model = "gpt-5.6-terra"
effort = "high"
timeout_s = 180

[review]
executor = "claude"
session_id = "review-session"
model = "sonnet"
effort = "high"
timeout_s = 180

[[tests]]
name = "pytest"
argv = [".venv/bin/python", "-m", "pytest", "-q"]
timeout_s = 900

[limits]
protocol_attempts = 3
worker_attempts = 12
changes_rounds = 5
process_retries = 3

[projection_limits]
max_file_bytes = 16384
max_file_lines = 200
max_total_bytes = 65536
```

`session_id` ist optional. Ohne sie legt ki-dev für die Rolle beim ersten
Aufruf eine neue Sitzung an und setzt sie in den weiteren Runden fort,
auch nach `resume` (abgelegt unter `<run>/sessions/<rolle>.json`). Eine
genannte `session_id` setzt eine bestehende Sitzung fort; `worker` und
`review` brauchen dann verschiedene. Optionale Felder dürfen entfallen; für
Grenzen gelten dann die eingebauten Werte, `data_mode` hat nur den Wert
`file_proposal`. Geprüft wird das Profil per JSON Schema
([`flow_ops/implement/config.py`](../src/ki_dev/flow_ops/implement/config.py)); die
Felder einer Rolle folgen aus dem Transport ihres Executors (siehe
[Executoren](#executoren)). Fehler nennen den Feldpfad, nie den Wert:

```
Profil .ki-dev/profiles/default.toml: worker: fehlende Felder ['model']
```

Der Umsetzer schreibt mit dem Dateizugriff aus `access_profile` (`write`
oder `read`), das Review nur lesend; die Adapter übersetzen das in die
Rechte ihrer CLI ([cli-adapters.md](cli-adapters.md)).

Das Manifest eines Laufs hält Pfad und SHA-256 der Profildatei fest;
`ki-dev -f implement status RUN_ID` zeigt sie unter `profile`.

## ki-dev getrennt vom Ziel-Repository installieren

`ki-dev` braucht eine eigene Python-Umgebung und muss im `PATH` liegen;
Ablaufpakete sucht es im aktuellen Verzeichnis (wie `make`, `bd`).

```bash
# B: ohne Container
pipx install /pfad/zu/ki-dev          # eigenes venv, ki-dev im PATH
cd ~/ziel-repo && ki-dev -f implement BEAD

# A: Ziel-Repository im eigenen Container; den ki-dev-Quellbaum als
#    Volume einbinden (agent-container: Referenzordner), darin
pipx install /references/ki-dev
```

Eine geerbte `PYTHONPATH` (etwa `/workspace/src` im ki-dev-Container)
geht jeder Installation vor: dann läuft der Quellbaum statt der
pipx-Kopie. Die Zeile `Ablauf: …/site-packages/ki_dev/flow/implement.toml`
auf stderr zeigt, welche greift; sonst `env -u PYTHONPATH ki-dev …`.

## Adapter je Rolle

| `executor` | Felder | Halt |
| --- | --- | --- |
| `claude`, `codex` | `session_id`, `model`, `effort`, optional `timeout_s`, `budget` | Schutzhalt (`execution_stopped`) bei Kontext-/Kontingentgrenze |
| `manual` | – | Eingabe auf stdout, formale Antwort von stdin (Ende mit Strg-D); leere Antwort → `awaiting_input`, danach `ki-dev -f implement resume RUN_ID` |
| `inbox` | – | Eingabe in `<runs>/<RUN_ID>/inbox/*.input.md` → `awaiting_input`; Antwort als `*.answer.md` daneben legen, dann `resume` |
| `mock` | Worker: optional `file`; Review: `answers` (Review-Ereignisse: `PASS`, `fix`, `decision`, `escalate`) | erschöpfte Antwortliste ist ein Prozessfehler |

`--adapter [ROLLE=]NAME` ersetzt den Executor einer Rolle (`worker`,
`review`) oder beider durch einen Executor ohne Sitzungsangaben
(`manual`, `inbox`, `mock`); `claude` und `codex` brauchen Sitzung und
Modell und stehen deshalb im Profil. Beim Start gilt der Ersatz für den
Lauf, bei `resume` nur für diesen Aufruf: das Manifest bleibt, die
genommene Kante nennt den Ersatz im Feld `adapter` von `events.jsonl`.

```bash
ki-dev -f implement resume RUN_ID --adapter review=manual   # Review einmal von Hand
``` Der Mensch als Bote ist damit für diesen Ablauf nur ein Adapter;
`ki-dev -f ABLAUF step` gibt dagegen zustandslos einzelne Übergaben
aus (Spielplatz, [step](step.de.md)).

`awaiting_input` ist ein Halt des Ausführers, kein Zustand des Ablaufs
(`AnswerPending` im Adaptervertrag, für jeden Transport gleich):
Der Lauf bleibt im aktuellen Zustand (`worker_step` bzw.
`controller_step`), die Operation bleibt offen und läuft nach der Antwort
erneut. `manual` und `inbox` deklarieren keine Messung; ki-dev bucht
für den Boten nichts.

Eine Entscheidung (`waiting_decision`, Zustand des Ablaufs) und eine Pause
(`paused_interactive`, Halt des Laufs nach einer Eskalation) setzt dagegen
`ki-dev -f implement resume RUN_ID --answer "…"` fort: bei der Entscheidung
über die Kante `resume_requested` zum Controller, bei der Pause im
Ablaufzustand, in dem eskaliert wurde (der Ablauf hat sich nicht bewegt).

Vollständig offline vorführen: `scripts/demo-mock-lauf.sh`.

## Worker-Umgebung

`workdir` bindet nicht nur den Prompt, sondern das tatsaechliche
Arbeitsverzeichnis des Agentenprozesses (`cwd`) und, ueber `_run_check`,
auch jeden konfigurierten Pruefauftrag. Eine reine Pfadangabe im Prompt
waere keine technische Bindung. `env` (optional, Standard leer)
ueberschreibt gezielt einzelne geerbte Umgebungsvariablen fuer beide --
Agententurn und Pruefauftraege --, ohne die uebrige geerbte Umgebung zu
ersetzen. Das ist noetig, wenn eine vom Aufrufer geerbte `PYTHONPATH`
sonst denselben Paketnamen aus einem fremden Quellstand (z. B. der
eigenen ki-dev-Installation) statt aus `workdir` aufloesen wuerde:
`cwd` allein schuetzt bei einem `src/`-Layout nicht davor.
Pruefauftraege bleiben Sache der Orchestrierung; der Worker prueft
gezielte Entwicklungsfaelle selbst, ohne die bekannte Umgebung neu
suchen zu muessen.

Der `workdir` ist der isolierte Bau-/Review-Worktree. `target_workdir` ist ein
zweiter, sauberer Worktree desselben Git-Repositories, der auf `target_ref`
steht. Vor dem Start stehen beide auf demselben Basiscommit. Damit ist der
vollständige Lauf ohne Kopieren von Agentennachrichten startbar; Bau und Review
werden aus der Konfiguration in getrennten Sitzungen fortgesetzt.

Der Lauf liegt unter `.ki-dev/runs/<run-id>/`: `record.json` enthält den
Datensatz (Lauf-Maschine, offene Operation, Ablaufzustand, Laufdaten), `manifest.json` den unveränderlichen Auftrag samt
Konfiguration, und einzelne JSON-Dateien enthalten unveränderliche
Operations- und Review-Nachweise. Vor jeder externen Wirkung speichert der
Ausführer die Absicht (`started`), danach das Ergebnis; endet der Prozess
dazwischen, ist der Lauf `uncertain`, außer die Operation gehört zum
wiederholbaren Abschlussweg. Ein Lauf hat genau einen Schreiber; ein
zweiter Aufruf für denselben Lauf wird abgewiesen. Die an den Reviewer übergebene Projektion
bleibt auch nach einem Neustart byte-, zeilen- und gesamtbegrenzt.

Bei `NEEDS_DECISION` und `ESCALATE` hält der Prozess dauerhaft an:

```bash
ki-dev -f implement resume run-42 --answer "Die gebundene Entscheidung"
```

Eine Eskalation führt nach Resume wieder zum Reviewer und niemals direkt zu
`PASS`. Wenn ein externer Aufruf nachweislich begonnen wurde, aber kein
Ergebnisartefakt existiert, meldet der Lauf `uncertain`. Er wiederholt den
Aufruf nicht automatisch. Damit verspricht der Ausführer keine unbelegbare
Exactly-once-Ausführung über Agentenprozesse, Git und Beads hinweg.
Nach einem manuellen Abgleich kann das erwartete JSON-Ergebnis der
angezeigten `operation_id` ausdrücklich übernommen werden:

```bash
ki-dev -f implement resume run-42 --reconcile-result abgeglichen.json
```

Ohne diesen expliziten Abgleich bleibt der Lauf angehalten.

## Auftragsbindung fuer CHANGES

`acceptance_criteria` ist eine nichtleere, eindeutige Liste bestehender
Anforderungen; sie ist Teil des unveraenderlichen Auftrags und bleibt
ueber Korrekturen und Resume stabil. Der Reviewer erhaelt sie durchnummeriert
als `AC1`, `AC2`, ... und muss ein `fix` (Urteil `CHANGES`) an genau eine
davon binden. `event` ist ein Review-Ereignis von `implement.toml`: `PASS`
oder eine Befundklasse (`fix`, `decision`, `escalate`); das Urteil folgt
aus `finding_class`:

```json
{"run_id":"run-42","round_id":2,"event":"fix","detail":"...","requirement_ref":"AC1"}
```

Ein `fix` ohne bekannte Referenz (fehlend, leer oder unbekannt) wird
nicht als Reparaturauftrag uebernommen, sondern automatisch zu
`decision` (`NEEDS_DECISION`) umgewandelt: mehrdeutige Anforderungen oder eine
strengere neue Interpretation brauchen eine menschliche Klaerung statt
einer automatisch gestarteten weiteren Baurunde. Ein Quelltext-Diff
allein ist dabei kein Ablehnungsgrund; geprueft wird nur die technische
Referenz, nicht die inhaltliche Berechtigung der Beanstandung. Alle
anderen Ereignisse (`PASS`, `decision`, `escalate`) duerfen kein
`requirement_ref` setzen. Eine freigegebene echte Auftragserweiterung
braucht einen neuen, gesondert gestarteten Lauf mit erweiterten
`acceptance_criteria` statt einer stillen Erweiterung des laufenden
Auftrags.

## Statusabfrage ohne Fortschreiben

```bash
ki-dev -f implement status run-42 --runs-dir .ki-dev/runs
```

Liest Status, Phase und Runden-ID aus dem zuletzt gespeicherten
Datensatz, ohne Bau/Review/Resume auszuführen und ohne eine Datei zu
schreiben. Der Datensatz wird je Schritt über `os.replace` ersetzt; ein
Leser sieht deshalb auch bei aktivem Schreiber immer einen ganzen Stand.
Fehlt der Lauf oder verletzt sein Datensatz das Schema, meldet das
Kommando das eindeutig (mit Feldpfad) statt eines erfundenen
Platzhalterstatus. Läufe aus der Zeit mit LangGraph-Checkpoint sind nicht
fortsetzbar; das Kommando sagt das ausdrücklich.

```bash
ki-dev -f implement history run-42 --runs-dir .ki-dev/runs
```

Erzählt denselben Lauf für Menschen aus seinen Artefakten: je Runde die
geänderten Dateien, die Prüfergebnisse und die Antwort des Reviews,
danach den Abschluss. Gelesen wird nur; je Runde zählt der letzte Versuch
einer Operation.

## Ereignisprotokoll je Übergang

Jeder genommene Übergang steht als eine Zeile in
`<runs>/<RUN_ID>/events.jsonl`, mit seiner Region: `ablauf` (Namen des
Ablaufs) oder eine Region des Laufs (`operation`, `halt`,
`runner/run.toml`):

```json
{"line": 12, "region": "ablauf", "seq": 7, "ts": "…", "flow": "implement", "run": "run-42", "state": "controller_step", "event": "fix", "target": "worker_step_prepare", "cond": ["checked_result"], "actions": ["begin_correction", "drop_result"], "escalation": null, "actor": "Controller (Review-Sitzung)", "adapter": "codex-cli"}
{"line": 13, "region": "operation", "seq": 7, "ts": "…", "flow": "run", "run": "run-42", "state": "idle", "event": "hold", "target": "prepared", "cond": ["is_running"], "actions": ["hold_operation"], "escalation": null, "actor": null, "adapter": "ki-dev"}
```

`line` zählt alle Zeilen; nach einem Absturz wird dieselbe Zeile nicht
doppelt geschrieben. `seq` ist die Revision des Ablaufs: nach einer
Ablaufkante die neue, bei einer Kante des Laufs die, in der sie
stattfand. So steht der Verlauf des Laufs (Operationen, Pausen,
Antworten) neben dem des Ablaufs, ohne dessen Zählung zu stören.
`adapter` nennt, wer das Ereignis brachte: bei einer Übergabe der
Executor, der antwortete (etwa `manual`), sonst `ki-dev`.
Beginnt ein neuer Lauf im selben Protokoll (`start` mit `again`),
steht davor die Zeile
`lauf --@start--> lauf` (Region `lauf`): die Regionen des Laufs beginnen
wieder im Anfangszustand. Beginnt der neue Lauf im selben Ablauf an
anderer Stelle, als der alte hielt, folgt `letzter Halt --@jump--> Start`.
`check_conformance` (`src/ki_dev/runner/events.py`) gleicht jede Region
gegen ihre Definition ab: den Ablauf gegen das Paket, `operation` und
`halt` gegen `runner/run.toml`; der Neubeginn ist konform, ein Sprung
nicht.
XES (IEEE 1849) ist bewusst nur ein möglicher späterer Export; die Felder
lassen sich direkt abbilden.

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
| `safety_limits.max_stagnant_changes` | 3 | Bei so vielen CHANGES in Folge an derselben `requirement_ref` (die aktuelle Runde eingeschlossen) kein weiterer automatischer Bau |
| `safety_limits.min_remaining_percent` | 10 | Zentrale, rollenunabhaengige Schutzreserve des Fuenfstundenkontingents (siehe unten); betrifft nicht `max_claude_cost_usd` (bezahlte Zusatznutzung) |
| `budget.max_usage_delta_percentage_points` je Rolle | 20 | Aufgaben-Delta-Budget des Fuenfstundenkontingents (siehe unten) |
| `worker.budget.max_turns` / `review.budget.max_turns` | 12 | Native Claude-Turn-Grenze pro Aufruf |
| `budget.max_budget_usd` je Rolle | 1 | Native Claude-Kostengrenze pro Aufruf |
| `budget.max_context_tokens` je Rolle | 80.000 | Kontextvorpruefung durch die Orchestrierung vor jedem Bau-/Review-Aufruf und bei Resume (siehe unten) |
| `budget.timeout_s` je Rolle | 180 s | Prozesstimeout fuer beide Adapter; der kleinere Wert aus Rollen-Timeout und Budget gilt. Eine vorgeschaltete CLI-Versionsprobe teilt sich diese Frist mit dem Turn, statt sie zu verdoppeln (siehe [cli-adapters.md](cli-adapters.md#versionsprobe-teilt-sich-die-zeitgrenze-mit-dem-turn)) |

Beispiel fuer eine bewusst kleinere Schranke auf oberster Konfigurationsebene:

```json
"safety_limits": {
  "max_agent_calls": 4,
  "max_total_tokens": 500000,
  "max_claude_cost_usd": 2,
  "max_failed_corrections": 1,
  "min_remaining_percent": 10
}
```

Die Rolle kann ein `budget`-Objekt mit den fuenf oben genannten Feldern
(inklusive `max_usage_delta_percentage_points`) enthalten. Nicht
angegebene Werte erhalten die Standardwerte; wirksame Rollenbudgets und
Laufgrenzen werden beim Start im Manifest gespeichert. `safety_limits`
ist ein vollstaendiger Satz: ein Altlauf, dessen gespeichertes Manifest
`min_remaining_percent` noch nicht enthaelt, startet nicht automatisch
neu (siehe `CallLedger.limits`).

`max_agent_calls`, `max_total_tokens`, `max_claude_cost_usd`,
`max_failed_corrections` und `max_stagnant_changes` sind konservative
Betriebsvorgaben, keine aus dem Abo abgeleiteten Werte -- ein CLI-Aufruf
kann viele interne Modellanfragen enthalten, und diese Zaehler bilden
weder das verbleibende Kontokontingent noch dessen Anteil ab. Ein
frueherer Lauf hat trotz greifender Zaehler das tatsaechliche
Fuenfstundenkontingent erreicht (`rate_limit`/HTTP 429/`five_hour`,
siehe [uar-2-02-verbrauch.md](ki-dev/uar-2-02-verbrauch.md)).
`max_usage_delta_percentage_points` und `min_remaining_percent` sind
deshalb keine weiteren Tokenzaehler, sondern echte, vom Executor
gemeldete Prozentgroessen des Kontokontingents; siehe
"Fuenfstundenkontingent-Vorpruefung" unten. Eine erste Fassung dieser
Pruefung mass einen absoluten Kontostand-Schwellenwert
(`max_five_hour_used_percent`, ki-dev-ablauf-hju); das war
inkonsistent mit jedem anderen Feld dieser Tabelle (alle sind
kumulative Budgets ab Laufstart, keine Kontostand-Momentaufnahmen) und
wurde durch das unten beschriebene Delta-/Reserve-Paar ersetzt
(ki-dev-ablauf-dqv).

### Executoren

Ein Executor ist Daten des Geruests
([`src/ki_dev/adapter/executors.toml`](../src/ki_dev/adapter/executors.toml)):
ein Name bindet einen Transport (Code je Anbieter) und deklariert die
Messungen, die der Ausfuehrer verlangt. Das Profil waehlt je Rolle nur
den Namen.

| Executor | Transport | `measures` |
| --- | --- | --- |
| `claude` | `claude-cli` | `context`, `quota`, `budget` |
| `codex` | `codex-cli` | `quota`, `budget` |
| `manual` | `console` | – |
| `inbox` | `inbox` | – |
| `mock` | `mock` | – |

Deklariert heisst Pflicht: fehlt der Messwert, haelt der Lauf. Nicht
deklariert heisst, der Waechter gilt nicht -- ohne `budget` wird der
Aufruf weder reserviert noch gezaehlt noch gebucht. Beim Laden prueft
`adapter/registry.py` (JSON Schema, dann benannte Pruefung), dass
`measures` nur enthaelt, was der Transport kann:

```
[executor.manual] transport = "console", measures = ["quota"]
→ executor.manual.measures: Transport console misst kein quota
```

### Kontextvorpruefung

Vor jedem Bau-/Review-Aufruf eines Executors mit `context` und bei
Resume misst der zustaendige Adapter
(`Executor.measure_context(session_id)`) den zuletzt bekannten
Sitzungskontext; **Freigabe, Halt und Persistenz entscheidet
ausschliesslich die Orchestrierung** (`flow_ops.implement.runtime._context_guard`),
nie eine Selbsteinschaetzung des Agenten oder eine Prompt-Anweisung.
Ein Adapter liefert nur den Messwert.

Der Messwert traegt eine von drei Herkunftsarten (`ContextStatus`):

| Herkunft | Bedeutung | Wirkung |
| --- | --- | --- |
| `measured` | echter Messwert vorhanden | `>= max_context_tokens` haelt vor dem Aufruf an |
| `unsupported` | der Transport bietet keine Messung, obwohl der Executor `context` deklariert | haelt vor dem Aufruf an |
| `unavailable` | Messung vorgesehen, aber gerade nicht lesbar (fehlende/mehrdeutige lokale Ablage einer genannten Sitzung) | haelt vor dem Aufruf an -- ein unbelegter Kontext gilt nicht als klein |

Eine Sitzung, die erst der Aufruf anlegt (ohne `session_id`), hat noch
keinen Kontext; fuer sie misst der Waechter nichts.

Eine erreichte oder unbelegte Grenze fuehrt vor dem naechsten externen
Aufruf zur Pause; die Meldung nennt Rolle, Executor, Sitzung, Messwert
(falls vorhanden), Grenze und Herkunft, und es entsteht eine Handoff-
Datei wie bei jeder anderen Eskalation. Ein kleiner Kontext ohne
weiteren Blocker laesst dieselbe Sitzung unveraendert weiterlaufen;
ein anderer Pausegrund (z. B. `NEEDS_DECISION`) kann trotz kleinem
Kontext ein Handoff erzeugen -- keiner der beiden Faelle erzwingt
einen Sitzungswechsel, und automatische Sitzungsrotation ist nicht
Teil dieses Mechanismus (siehe "Kompakte Sitzungsuebergabe" oben).
Resume prueft den dann aktuellen Messwert erneut, nicht den
urspruenglichen.

### Fuenfstundenkontingent-Vorpruefung

Geplanter Ausbau (2026-09-17):
[Tokenmessung und Estimatoren](architecture/tokenmessung-estimatoren.de.md)
beschreibt normalisierte Verbrauchsbilanzen, Mehrmodell-Schnittpruefung und
kalibrierte Prognosen. Diese Erweiterungen sind noch kein Runtime-Verhalten.
Vor dem naechsten echten Laufnachweis ist zusaetzlich der manuelle Messabgleich
`ki-dev-ablauf-wu0.1` erforderlich; er blockiert in Beads `ki-dev-ablauf-uar.2`.
Die nachfolgend beschriebenen bestehenden Guards bleiben unabhaengig davon
wirksam.

Vor jedem Bau-/Review-Aufruf eines Executors mit `quota` und bei
Resume misst der zustaendige Adapter
(`Executor.measure_quota(session_id)`) den zuletzt bekannten
Verbrauchsanteil des rollierenden Fuenfstundenfensters des
Kontokontingents; **Freigabe, Halt und Persistenz entscheidet
ausschliesslich die Orchestrierung** (`flow_ops.implement.runtime._quota_guard`),
nie eine Selbsteinschaetzung des Agenten. Ein Adapter liefert nur den
Messwert.

Zwei unabhaengige, gemeinsam ausgegebene Pausengruende (keine
Kurzschluss-Auswertung -- eine erreichte Grenze verdeckt nicht, dass
auch die andere greift, `flow_ops.implement.runtime._call_guards`):

1. **Aufgaben-Delta-Budget** (`budget.max_usage_delta_percentage_points`,
   je Rolle): wie viele Prozentpunkte das beobachtete, kontoweite
   Kontingent seit der Basislinie dieser Rolle im aktuellen
   Fuenfstundenfenster gewachsen ist. Ein konservatives Pausesignal,
   keine exakte Zurechnung -- paralleler Verbrauch derselben Rolle
   *und* anderer Sitzungen desselben Kontos zaehlt mit (das
   Kontingent ist kontoweit, siehe unten).
2. **Zentrale Schutzreserve** (`safety_limits.min_remaining_percent`):
   haelt an, sobald fuer diese Rolle kaum noch Kontingent uebrig ist,
   unabhaengig vom Aufgabenbudget.

Beides ist eine Pause-Schwelle vor dem naechsten Aufruf, keine harte
Echtzeitgrenze: ein einzelner Aufruf kann sie ueberschreiten, da er
nicht unterbrochen werden kann.

Anders als bei der Kontextvorpruefung gibt es hier keinen Status, der
einen Aufruf freigibt, ausser einem tatsaechlichen Messwert -- fuer ein
Kontokontingent gibt es keine sichere Annahme "kein Nachweis = ok":

| Herkunft (`QuotaStatus`) | Bedeutung | Wirkung |
| --- | --- | --- |
| `measured` | echter, vom Executor gemeldeter Prozentwert | Delta- und Reserve-Pruefung wie oben |
| `pending` | der Adapter misst erst mit der Antwort und hat noch keinen aktuellen Wert (neue Sitzung, `claude-cli` vor dem ersten Turn oder nach Fensterwechsel, `codex-cli` ohne aktuellen Kontowert; siehe [cli-adapters.md](cli-adapters.md)) | laesst den Aufruf zu; Reserve und Delta greifen ab dem naechsten |
| `unsupported` | dieser Adapter liefert keinen verbrauchsfreien, nicht-interaktiven Nachweis | haelt an, als eigene Ursache "Messwert fehlt" gemeldet |
| `unavailable` | Messung vorgesehen, aber gerade nicht lesbar (z. B. Codex-Rollout fehlt/mehrdeutig, oder die Sitzung hat seit dem letzten Messwert ohne Messwert geantwortet) | haelt an, ebenfalls als "Messwert fehlt" gemeldet, nie vermischt mit "Budget/Reserve erreicht" |

`codex-cli` liest dazu verbrauchsfrei die lokale Rollout-Ablage unter
`~/.codex/sessions/JJJJ/MM/TT/rollout-*-<session_id>.jsonl` und nimmt
das `token_count`-Ereignis mit dem 5h-Fenster (`window_minutes == 300`)
im Kontingent-Topf des Kontos (`limit_id` `codex`).
Das Kontingent ist **kontoweit, nicht sitzungsgebunden**: die eigene
Sitzung einer Rolle kann laenger nicht mit der API gesprochen haben,
waehrend eine andere Sitzung desselben Kontos es zwischenzeitlich
weiter verbraucht hat -- ein noch nicht abgelaufenes Fenster beweist
keinen aktuellen Kontostand. Gemessen wird deshalb das zeitlich
juengste `token_count`-Ereignis ueber ALLE lokalen Rollouts, nicht nur
die der eigenen Sitzung; `session_id` bleibt eine Gueltigkeitspruefung,
nicht die Messquelle (`codex_quota.codex_quota`). Die Suche liest jede
Rollout-Datei vollstaendig, ohne Fruehabbruch nach Datei-
Aenderungszeit: eine Beziehung zwischen der Aenderungszeit einer Datei
und dem in ihrem Inhalt stehenden Ereignis-Zeitstempel ist technisch
nicht garantiert (Kopien, Wiederherstellung, verzoegertes Schreiben)
und traegt deshalb keine Suchbegrenzung, solange eine solche Beziehung
nicht nachweisbar gilt. Der Vergleich laeuft -- sowohl zwischen
Dateien als auch innerhalb einer einzelnen Datei -- ueber geparste
Zeitwerte, nicht ueber die Zeitstempel-Strings selbst
(unterschiedliche Nachkommastellen-Laenge sortiert als Text falsch,
`...:00Z` nach `...:00.500Z`, obwohl Ersteres frueher ist) und nicht
ueber die physische Zeilenreihenfolge (eine chronologisch sortierte
Zeilenfolge innerhalb einer Rollout-Datei ist technisch nicht
garantiert).

Drei zusaetzliche Bedingungen, bevor ein Messwert als Nachweis gilt:
ein Messwert, dessen Fenster laut `resets_at` bereits zurueckgesetzt
ist, gilt nicht als `0`, sondern als `unavailable`; ein Messwert mit
einem Ereignis-Zeitstempel merklich nach der aktuellen Zeit (jenseits
einer kleinen Uhrtoleranz, `CLOCK_SKEW_TOLERANCE_S`) gilt als
unplausibel, nicht als "besonders frisch"; und ein Messwert gilt nur
bis `MAX_MEASUREMENT_AGE_S` (Standard 1800 s) nach seinem eigenen
Ereignis-Zeitstempel als hinreichend aktuell -- ein noch nicht
abgelaufenes Fenster allein beweist keine Aktualitaet, ein Messwert
kann Stunden alt und trotzdem technisch "im Fenster" sein. Diese
Altersschwelle begrenzt Unsicherheit, garantiert aber keinen
tatsaechlich aktuellen Kontostand; ohne live abfragbaren Kontostand ist mehr lokal nicht beweisbar. Die
Kontozuordnung der durchsuchten lokalen Ablage (`CODEX_HOME` bildet
durchgehend genau ein Konto ab) ist eine dokumentierte, technisch
nicht pruefbare Betriebsvoraussetzung -- weder `session_meta` noch
`rate_limits` tragen ein Kontomerkmal; die Altersschwelle mindert
dieses Risiko zusaetzlich, da nur kuerzlich aktive Daten ueberhaupt
als Nachweis akzeptiert werden.

Die Basislinie fuer das Delta-Budget ist rollengebunden, liegt unter
`<run>/quota/<rolle>.json` und ueberlebt Resume unveraendert
(`runner.safety.QuotaBaseline`). Ein echter Fensterrollover (`resets_at`
steigt gegenueber der gespeicherten Basislinie) setzt sie bewusst neu
auf `0` -- das Kontingent hat sich real erneuert, ein neues Budget pro
Fenster ist beabsichtigt, kein kumulatives Aufgabenbudget ueber
Fenstergrenzen hinweg. Ein `resets_at`, das gegenueber der Basislinie
*zurueckgeht*, ist dagegen kein legitimer neuer Fensterstand, sondern
ein widerspruechlicher Messwert und wird als eigener Pausengrund
gemeldet, nicht als stiller Reset uebernommen.

`claude-cli` hat keinen Messweg vor einem Aufruf: Claude Code liefert
den 5h-Anteil verbrauchsfrei nur mit einer Antwort (`rate_limit_event`
in `stream-json --verbose`). Der Adapter legt ihn nach jedem Turn ab
und meldet vor dem ersten Turn `pending`. **Der erste Aufruf einer
Sitzung ist darum ungemessen** und nur durch den reaktiven Halt
(`rate_limit`/HTTP 429) geschuetzt; die Delta-Basislinie entsteht mit
dem Wert nach diesem Aufruf.

`calls/` enthaelt unveraenderliche Start- und Ergebnisbelege mit
Verbrauch, Dauer und Fehlergrund. Die Reservierung vor einem Aufruf
wird gesperrt gegen gleichzeitige Reservierungen; ein Neustart setzt
keinen Zaehler zurueck. Die Bilanz zaehlt Cache-Lesetokens mit und
vermeidet bei Codex deren Doppelzaehlung als ungecachten Input.

Ein Agentenfehler, verweigerte Berechtigung, Kontingentabbruch, fehlender
Verbrauchsnachweis oder eine erreichte Grenze fuehrt zu einer
Maschineneskalation `execution_guard` und zum Halt `paused_interactive`
(Lauf; der Ablauf bleibt stehen) mit Übergabe. Es folgt kein automatischer Agenten-Retry.
Das gilt auch fuer unbekannte CLI-Fehler; sie gelten nicht ohne Nachweis
als voruebergehend. Fachliche Review-Nachrichten bleiben davon getrennt.

## Kompakte Sitzungsuebergabe statt unbegrenztem Resume

Je Rolle gibt es eine Sitzung: genannt im Profil oder beim ersten Aufruf
von ki-dev angelegt (siehe Profil oben). ki-dev rotiert sie nicht
selbst -- das waere ein eigenstaendiger Mechanismus, den dieses Design
nicht vorsieht. Jede Pause (`paused_interactive`) und jeder Halt in
`waiting_decision` -- Verbrauchsgrenze, Kontextvorpruefung, Stillstand,
Agentenfehler, erschoepfte Protokoll-/Prozessversuche, Reviewer-Urteil
`ESCALATE`/`NEEDS_DECISION` -- schreibt stattdessen unter
`<run>/handoff/` eine kompakte, auftragsgebundene Uebergabe:
Auftrag und Abnahmekriterien, massgebliche Quellen, die noch offene
bzw. bereits abgeloeste `requirement_ref`, die bisher verworfenen
Korrekturversuche (Runde, Referenz, Begruendung -- kein Bau-/Review-
Transkript) und der bisher belegte Verbrauch. Ein Mensch entnimmt der
juengsten Datei genau das, was eine frisch vorbereitete Rollensitzung
braucht, statt den wachsenden Sitzungsverlauf per `--resume`
unbegrenzt fortzusetzen. Rollentrennung, Provenienz und die
bestehende Verbrauchsbilanz bleiben dabei erhalten; ein Sitzungswechsel
ist kein Budgetreset (siehe "Eskalation bei Stillstand").

## Eskalation bei Stillstand

Fortschritt heisst: eine andere oder geloeste `requirement_ref` (siehe
"Auftragsbindung fuer CHANGES"), nicht mehr Diff-Zeilen, mehr gruene
Tests oder dieselbe geaenderte Datei. Bindet der Reviewer
`max_stagnant_changes` CHANGES in Folge an dieselbe Referenz, haelt
der Lauf vor dem naechsten Bauaufruf an -- unabhaengig davon, ob jeder
einzelne Befund fuer sich reparierbar wirkt. Die Meldung nennt
Referenz, Anzahl der Wiederholungen und den bisher aus `calls/`
belegten Verbrauch. Die Serie wird bei jeder Pruefung aus den
persistierten Review-Nachrichten neu berechnet; ein Neustart,
Sitzungswechsel oder eine Antwort setzt sie nicht zurueck. Nach der
Klaerung (`ki-dev -f implement resume --answer ...`) prueft derselbe Reviewer
dieselbe Runde erneut, statt automatisch denselben unveraenderten
Reparaturansatz erneut zu bauen; Verbrauchsgrenzen bleiben dabei
wirksam.

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

`PASS` ist noch kein Erfolg. Der Ausführer bindet es zunächst an den exakten,
zuletzt geprüften Commit sowie dessen Baum-ID. Anschließend erzeugt er einen
kompakten Commit mit dem Laufbasiscommit als Parent und exakt demselben Baum.
Nur wenn Quell- und Zielarbeitsbaum sauber sind, der geprüfte Commit noch
unverändert ist, der Zielbranch noch auf der Laufbasis steht und beide Baum-IDs
identisch sind, führt er im Ziel-Worktree `git merge --ff-only` aus. Erst die
erneute Prüfung des integrierten Commit und Baums ergibt `passed` / `PASSED`.

Alle vier Abschlussoperationen besitzen unveränderliche Artefakte. Nach einem
Prozessabbruch genügt daher:

```bash
ki-dev -f implement resume run-42
```

Eine bereits nachgewiesene Integration wird dabei nicht wiederholt. Ein
negatives Drift-Gate pausiert; nachdem die äußere Ursache behoben wurde, wird
dieselbe Phase mit einer gebundenen Bedienerantwort erneut geprüft:

```bash
ki-dev -f implement resume run-42 --answer "Zielstand extern geprüft und korrigiert"
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

## Begrenzte Review-Projektion

`project_review_context` (`review_context.py`) begrenzt, was der Reviewer je
Runde tatsaechlich sieht -- `projection_limits` (siehe oben) je Datei und
insgesamt, unabhaengig davon, wie gross Delta oder Laufhistorie wirklich sind:

- Laufzeit-/Cache-/interne Dolt-Pfade (`.ki-dev`, `.beads/*` ausser
  `issues.jsonl`, `.venv`, `__pycache__`, `.pytest_cache`, `.ruff_cache`,
  `.hypothesis`, `.loope`) werden nie als Diff-Inhalt uebergeben, beliebig
  tief verschachtelt.
- Binaerdateien erscheinen nur als Pfad, Aenderungsart und Git-Blob-Referenz
  (`index=<a>..<b>` aus dem Diff, falls vorhanden), nie als Binaerpatch/Base64.
- Generierte Lockfiles (`package-lock.json`, `yarn.lock`, `poetry.lock`,
  `Cargo.lock`, `go.sum`, ...) erscheinen zunaechst nur als Zeilen-Statistik;
  volle Details kommen ausschliesslich per gezieltem Nachladen
  (`preferred_paths`, s. u.).
- Jede Auslassung (Laufzeitpfad, Binaerinhalt, Lockfile-Zusammenfassung,
  Zeilen-/Byte-/Gesamtgrenze) wird als `OMITTED [<referenz>] reason=<grund>`
  festgehalten; die Projektion behauptet nie stillschweigend Vollstaendigkeit.
- Auch ein einzelner, sehr grosser JSON-Einzeiler faellt unter die
  Byte-Grenze je Datei, unabhaengig von der Zeilenzahl.

`preferred_paths` ist der einzige Nachlademechanismus: nur Pfade des
aktuellen Schrittdeltas sind zulaessig, sie werden zuerst einsortiert und
umgehen fuer Lockfiles die Zusammenfassung -- ohne Datei- oder
Gesamtgrenzen zu lockern. Ein abschliessender Review sieht sowohl den
Schrittdelta als auch den kumulierten Laufdelta seit Laufbeginn; reicht der
Nachweis wegen Begrenzung nicht aus, ist gezieltes Nachladen oder ein Stopp
angezeigt, kein unbegruendetes PASS.
