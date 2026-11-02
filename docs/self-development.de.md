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
ki-dev -f implement BEAD_ID --profile ./probe.toml
ki-dev -f implement status RUN_ID
ki-dev -f implement resume RUN_ID
```

Die Laufdaten liegen unter `${XDG_STATE_HOME:-~/.local/state}/ki-dev/runs/`,
je Repo ein Ordner; `--runs-dir` wählt einen anderen.

## Agenten und Prüfbefehle im Container

ki-dev läuft auf dem Host aus `~/.local`, Agenten und `[[tests]]` laufen im
Agent-Container. So ändert der entwickelte Code den laufenden Runner nicht,
und der Agent erreicht weder Runner noch Laufdaten. Einschalten im Profil:

```toml
workdir = "/pfad/zu/ki-dev/.local/var/lauf/bau"

[container]              # launcher: Standard ist die Kopie aus make setup-runtime
```

```bash
./scripts/agent-container build      # Image; wiederholen, wenn es sich ändert
make setup-runtime                   # ki-dev und Launcher nach ~/.local
git worktree add --detach .local/var/lauf/bau main
~/.local/bin/ki-dev -f implement BEAD_ID --profile ./probe.toml
```

Den Worktree **auf dem Host** anlegen: `bau/.git` enthält einen absoluten
Pfad, und der Container bindet ihn unter demselben Pfad ein. Er muss in einem
für Docker freigegebenen Ordner liegen, sonst bricht der Start mit Exit 125 ab.
`[[tests]]` laufen mit den Programmen des Images; `/workspace/.venv` enthält
die Abhängigkeiten des Images, `/workspace` selbst ist leer. ki-dev nicht in
`bau` starten: Es sucht Ablaufpakete und Profile im Startordner, und den Inhalt
von `bau` kann der Agent ändern.

Was der Container sieht und was nicht, steht in
[docker/agent/README.md](../docker/agent/README.md#worktree-modus---workdir).

Für den Umsetzungsablauf im Profil getrennte Bau- und Ergebnis-Worktrees
konfigurieren, wie in [Ausführer und Laufzeit](ausfuehrer.de.md) beschrieben.
Das Setup erzeugt weder Worktrees noch Profile oder Agentensitzungen.
`make setup-runtime` installiert nur ki-dev; `bd` und die Agenten-CLIs müssen
im PATH verfügbar sein. Der installierte Einstieg startet Python isoliert
und entfernt geerbtes `PYTHONPATH`/`PYTHONHOME`, damit der Betriebsprozess
die Installation nutzt. Die Worker-Umgebung wird weiterhin im Profil gesetzt.

`make readme-check` prüft Installation, Trennung vom Arbeitsbaum und
erneutes Update in einem Wegwerf-Container ohne Anbieteraufrufe.
