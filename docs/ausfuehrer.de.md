# Ausführer: `ki-dev run`

Der Ausführer fährt einen deklarativen Ablauf
([`src/ki_dev/flow/delivery.toml`](../src/ki_dev/flow/delivery.toml)) bis zum
nächsten Halt. Er liest die formale Antwort eines Adapters, macht daraus
ein Ereignis, wählt mit den Wächtern des Ablaufs die Kante, führt deren
Aktion aus und gibt die nächste Eingabe aus. Eine eigene Topologie hat er
nicht: Welche Operation in welchem Zustand läuft (`operation`), welche
Korrekturrunde noch erlaubt ist und wohin ein Schutzhalt führt, steht im
Ablauf. LangGraph liefert Checkpoint, Halt und Fortsetzung.

Ein neuer Lauf wird mit einer expliziten JSON-Konfiguration gestartet:

```bash
ki-dev run --config lauf.json --run-id run-42
```

```json
{
  "task": "Den beschriebenen Auftrag umsetzen",
  "acceptance_criteria": [
    "Konkretes, pruefbares Kriterium 1",
    "Konkretes, pruefbares Kriterium 2"
  ],
  "sources": ["bd:projekt-42", "docs/vertrag.md"],
  "workdir": "/absoluter/pfad/zum/repository",
  "access_profile": "write",
  "env": {
    "PYTHONPATH": "/absoluter/pfad/zum/repository/src"
  },
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

## Adapter je Rolle

| `executor` | Felder | Halt |
| --- | --- | --- |
| `claude`, `codex` | `session_id`, `model`, `effort`, optional `timeout_s`, `budget` | Schutzhalt (`execution_stopped`) bei Kontext-/Kontingentgrenze |
| `manual` | keine | `awaiting_input`: Eingabe in `<runs>/<RUN_ID>/eingang/*.eingabe.md`, Antwort als `*.antwort.md` daneben, dann `ki-dev run resume RUN_ID` |
| `mock` | Bau: optional `datei`; Review: `antworten` (`PASS`, `CHANGES`, `NEEDS_DECISION`) | erschöpfte Antwortliste ist ein Prozessfehler |

`awaiting_input` ist ein Halt des Ausführers, kein Zustand des Ablaufs:
Der Lauf bleibt im aktuellen Zustand (`worker_step` bzw.
`controller_step`), die Operation bleibt offen und läuft nach der Antwort
erneut. Der Bote verbraucht kein Agentenbudget von ki-dev.

Halt mit Zustand des Ablaufs (`waiting_decision`, `paused_interactive`)
setzt dagegen `ki-dev run resume RUN_ID --answer "…"` fort; das ist die
Kante `resume_requested`, bei einer Pause zurück zum Fortsetzungspunkt.

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

Der Lauf liegt unter `.ki-dev/runs/<run-id>/`: SQLite enthält die
LangGraph-Checkpoints, `manifest.json` den unveränderlichen Auftrag samt
Konfiguration, und einzelne JSON-Dateien enthalten unveränderliche
Operations- und Review-Nachweise. Die an den Reviewer übergebene Projektion
bleibt auch nach einem Neustart byte-, zeilen- und gesamtbegrenzt.

Bei `NEEDS_DECISION` und `ESCALATE` hält der Prozess dauerhaft an:

```bash
ki-dev run resume run-42 --answer "Die gebundene Entscheidung"
```

Eine Eskalation führt nach Resume wieder zum Reviewer und niemals direkt zu
`PASS`. Wenn ein externer Aufruf nachweislich begonnen wurde, aber kein
Ergebnisartefakt existiert, meldet der Lauf `uncertain`. Er wiederholt den
Aufruf nicht automatisch. Damit verspricht der Ausführer keine unbelegbare
Exactly-once-Ausführung über Agentenprozesse, Git und Beads hinweg.
Nach einem manuellen Abgleich kann das erwartete JSON-Ergebnis der
angezeigten `operation_id` ausdrücklich übernommen werden:

```bash
ki-dev run resume run-42 --reconcile-result abgeglichen.json
```

Ohne diesen expliziten Abgleich bleibt der Lauf angehalten.

## Auftragsbindung fuer CHANGES

`acceptance_criteria` ist eine nichtleere, eindeutige Liste bestehender
Anforderungen; sie ist Teil des unveraenderlichen Auftrags und bleibt
ueber Korrekturen und Resume stabil. Der Reviewer erhaelt sie durchnummeriert
als `AC1`, `AC2`, ... und muss ein `CHANGES` an genau eine davon binden:

```json
{"run_id":"run-42","round_id":2,"action":"CHANGES","detail":"...","requirement_ref":"AC1"}
```

Ein `CHANGES` ohne bekannte Referenz (fehlend, leer oder unbekannt) wird
nicht als Reparaturauftrag uebernommen, sondern automatisch zu
`NEEDS_DECISION` umgewandelt: mehrdeutige Anforderungen oder eine
strengere neue Interpretation brauchen eine menschliche Klaerung statt
einer automatisch gestarteten weiteren Baurunde. Ein Quelltext-Diff
allein ist dabei kein Ablehnungsgrund; geprueft wird nur die technische
Referenz, nicht die inhaltliche Berechtigung der Beanstandung. Alle
anderen Aktionen (`PASS`, `NEEDS_DECISION`, `ESCALATE`) duerfen kein
`requirement_ref` setzen. Eine freigegebene echte Auftragserweiterung
braucht einen neuen, gesondert gestarteten Lauf mit erweiterten
`acceptance_criteria` statt einer stillen Erweiterung des laufenden
Auftrags.

## Statusabfrage ohne Fortschreiben

```bash
ki-dev run status run-42 --runs-dir .ki-dev/runs
```

Liest Status, Phase und Runden-ID des zuletzt persistierten Checkpoints,
ohne Bau/Review/Resume auszufuehren und ohne den Lauf inhaltlich zu
veraendern. Die Momentaufnahme laeuft ueber SQLites Online-Backup-API
(Snapshot-Isolation): ein aktiver Schreiber mit offener WAL-Datei wird
konsistent gelesen, nicht blockiert und sein Datenstand nicht veraendert,
auch wenn waehrend der Aufnahme ein Checkpoint dazwischenkommt. Fehlt
zu einer WAL-Datei die zugehoerige SHM-Datei (z. B. nach einem Absturz),
legt das Lesen genau diesen notwendigen Sidecar neu an -- keine
Kopiereigenheit, sondern SQLites eigene Koordination fuer den
WAL-Index; Haupt- und WAL-Datei selbst bleiben dabei byteidentisch.
Fehlt der Lauf oder ist sein Checkpoint unvollstaendig, meldet das
Kommando das eindeutig statt eines erfundenen Platzhalterstatus.

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
| `build.budget.max_turns` / `review.budget.max_turns` | 12 | Native Claude-Turn-Grenze pro Aufruf |
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

### Kontextvorpruefung

Vor jedem Bau-/Review-Aufruf und bei Resume misst der zustaendige
Adapter (`Executor.measure_context(session_id)`) den zuletzt bekannten
Sitzungskontext; **Freigabe, Halt und Persistenz entscheidet
ausschliesslich die Orchestrierung** (`runner.runtime._context_guard`),
nie eine Selbsteinschaetzung des Agenten oder eine Prompt-Anweisung.
Ein Adapter liefert nur den Messwert.

Der Messwert traegt eine von drei Herkunftsarten (`ContextStatus`):

| Herkunft | Bedeutung | Wirkung |
| --- | --- | --- |
| `measured` | echter Messwert vorhanden | `>= max_context_tokens` haelt vor dem Aufruf an |
| `unsupported` | dieser Adapter bietet grundsaetzlich keine Messung (aktuell Codex, siehe [cli-adapters.md](cli-adapters.md)) | kein Blocker -- bekannter, dokumentierter Adaptergrenzfall |
| `unavailable` | Messung vorgesehen, aber gerade nicht lesbar (fehlende/mehrdeutige lokale Ablage, aktuell moeglich bei Claude fuer eine Sitzung ohne vorherigen realen Turn) | haelt vor dem Aufruf an -- ein unbelegter Kontext gilt nicht als klein |

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

Vor jedem Bau-/Review-Aufruf und bei Resume misst der zustaendige
Adapter (`Executor.measure_quota(session_id)`) den zuletzt bekannten
Verbrauchsanteil des rollierenden Fuenfstundenfensters des
Kontokontingents; **Freigabe, Halt und Persistenz entscheidet
ausschliesslich die Orchestrierung** (`runner.runtime._quota_guard`),
nie eine Selbsteinschaetzung des Agenten. Ein Adapter liefert nur den
Messwert.

Zwei unabhaengige, gemeinsam ausgegebene Pausengruende (keine
Kurzschluss-Auswertung -- eine erreichte Grenze verdeckt nicht, dass
auch die andere greift, `runner.runtime._call_guards`):

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
| `unsupported` | dieser Adapter liefert (noch) keinen verbrauchsfreien, nicht-interaktiven Nachweis (aktuell `claude-cli`, siehe [cli-adapters.md](cli-adapters.md)) | haelt an, als eigene Ursache "Messwert fehlt" gemeldet -- kein unbedenklicher Adaptergrenzfall wie bei der Kontextvorpruefung |
| `unavailable` | Messung vorgesehen, aber gerade nicht lesbar (z. B. Codex-Rollout fehlt/mehrdeutig oder Messwert abgelaufen) | haelt an, ebenfalls als "Messwert fehlt" gemeldet, nie vermischt mit "Budget/Reserve erreicht" |

`codex-cli` liest dazu verbrauchsfrei die lokale Rollout-Ablage unter
`~/.codex/sessions/JJJJ/MM/TT/rollout-*-<session_id>.jsonl` und nimmt
das `token_count`-Ereignis mit dem 5h-Fenster (`window_minutes == 300`).
Das Kontingent ist **kontoweit, nicht sitzungsgebunden**: die eigene
Sitzung einer Rolle kann laenger nicht mit der API gesprochen haben,
waehrend eine andere Sitzung desselben Kontos es zwischenzeitlich
weiter verbraucht hat -- ein noch nicht abgelaufenes Fenster beweist
keinen aktuellen Kontostand. Gemessen wird deshalb das zeitlich
juengste `token_count`-Ereignis ueber ALLE lokalen Rollouts, nicht nur
die der eigenen Sitzung; `session_id` bleibt eine Gueltigkeitspruefung,
nicht die Messquelle (`metering.codex_quota`). Die Suche liest jede
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
tatsaechlich aktuellen Kontostand; ohne live abfragbaren Kontostand
(siehe oben, `claude-cli`) ist mehr lokal nicht beweisbar. Die
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

`claude-cli` hat aktuell keinen verifizierten, verbrauchsfreien,
nicht-interaktiven Messweg: Claude Code liefert den Prozentwert nur an
ein interaktives `statusLine`-Skript und `/usage`; die lokale
Sitzungsablage traegt das Feld auch bei Erfolg nicht, sondern nur
reaktiv im Fehlerfall (`quotaLimits` bei HTTP 429) -- zu spaet fuer
eine Vorabpruefung. Ein Bau- oder Review-Lauf mit `claude-cli` haelt
deshalb bereits vor dem ersten Aufruf an, bis ein solcher Messweg
existiert und getestet ist. **Ein `claude-cli`-Lauf gilt bis dahin
nicht als gegen das Fuenfstundenkontingent abgesichert**, unabhaengig
von `max_total_tokens` (ki-dev-ablauf-hju, ueberarbeitet in dqv).

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

## Kompakte Sitzungsuebergabe statt unbegrenztem Resume

Sitzungen sind aufrufergebunden vorbereitet (getrennte `session_id` je
Rolle, siehe uar.1); ki-dev provisioniert oder rotiert sie nicht selbst
-- das waere ein eigenstaendiger Mechanismus, den dieses Design nicht
vorsieht. Jeder Halt nach `paused_interactive` oder
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
Klaerung (`ki-dev run resume --answer ...`) prueft derselbe Reviewer
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
ki-dev run resume run-42
```

Eine bereits nachgewiesene Integration wird dabei nicht wiederholt. Ein
negatives Drift-Gate pausiert; nachdem die äußere Ursache behoben wurde, wird
dieselbe Phase mit einer gebundenen Bedienerantwort erneut geprüft:

```bash
ki-dev run resume run-42 --answer "Zielstand extern geprüft und korrigiert"
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
