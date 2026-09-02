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
| `TurnRequest` | Eingabe: `session_id`, `message`, `model`, `effort` |
| `Effort` | `LOW` / `MEDIUM` / `HIGH` |
| `TurnResult` | Ausgabe: `status`, `exit_code`, `stdout`, `stderr`, `argv`, `duration_s`, `error` |
| `TurnStatus` | `OK` / `NONZERO_EXIT` / `TIMEOUT` / `START_ERROR` |
| `Executor` | Protokoll mit `name` und `send_turn(request) -> TurnResult` |

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

## ClaudeCliAdapter

Verwendete CLI: **Claude Code CLI** (`claude`), nachweisbar per
`claude --version`.

* **Verifizierter Bezugsstand:** Claude Code **2.1.257**
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
  (gueltige Werte in 2.1.257: `low`, `medium`, `high`, `xhigh`,
  `max`). Die drei Vertragsstufen werden unveraendert durchgereicht.

## CodexCliAdapter

Verwendete CLI: **OpenAI Codex CLI** (`codex`), nachweisbar per
`codex --version`.

* **Verifizierter Bezugsstand:** Codex CLI **0.152.0**
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
