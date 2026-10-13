# ki-dev am eigenen Repository entwickeln

```bash
cd /pfad/zu/ki-dev
make setup-runtime
export PATH="$HOME/.local/bin:$PATH"
```

Das Ziel installiert den aktuellen Arbeitsstand ohne Editable-Verknüpfung
in `${XDG_DATA_HOME:-$HOME/.local/share}/ki-dev/venv` und verlinkt
`~/.local/bin/ki-dev` auf dessen ausführbare Datei. Python ≥ 3.12 mit `venv`
und erreichbare Paketquellen sind erforderlich. Ein anderer Interpreter
kann über `KI_DEV_SETUP_PYTHON=/pfad/python3.12` gewählt werden.
Vorhandene fremde Dateien oder Symlinks werden nicht überschrieben.

Im Entwicklungsrepo bleiben `make setup` und `.venv` für Tests verfügbar.
Arbeitsbaumänderungen beeinflussen die Betriebsinstallation erst nach einem
erneuten `make setup-runtime`, auch wenn die Paketversion gleich bleibt.

**Bekannte Grenze des Erstumfangs:** Vor jedem Runtime-Update alle aktiven
und pausierten Läufe abschließen. Das Update ersetzt eine Installation;
es gibt keine Versionsverwaltung oder automatische Laufprüfung. Nach einem
fehlgeschlagenen Update vor dem nächsten Lauf die Installation reparieren.

Ein vorbereitetes lokales Profil wird direkt an ki-dev übergeben:

```bash
RUNS="${XDG_STATE_HOME:-$HOME/.local/state}/ki-dev/runs"
ki-dev -f implement BEAD_ID --profile ./probe.toml --runs-dir "$RUNS"
ki-dev -f implement status RUN_ID --runs-dir "$RUNS"
ki-dev -f implement resume RUN_ID --runs-dir "$RUNS"
```

Für den Umsetzungsablauf im Profil getrennte Bau- und Ergebnis-Worktrees
konfigurieren, wie in [Ausführer und Laufzeit](ausfuehrer.de.md) beschrieben.
Das Setup erzeugt weder Worktrees noch Profile oder Agentensitzungen.
`make setup-runtime` installiert nur ki-dev; `bd` und die Agenten-CLIs müssen
im PATH verfügbar sein. Der installierte Einstieg startet Python isoliert
und entfernt geerbtes `PYTHONPATH`/`PYTHONHOME`, damit der Betriebsprozess
die Installation nutzt. Die Worker-Umgebung wird weiterhin im Profil gesetzt.

`make readme-check` prüft Installation, Trennung vom Arbeitsbaum und
erneutes Update in einem Wegwerf-Container ohne Anbieteraufrufe.
