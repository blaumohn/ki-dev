# Agenten im Docker-Container

Die Laufzeitkonfiguration steht zentral in `compose.yaml`. Das Startskript
ruft Docker Compose auf und behält pro Repo dieselben Home-/venv-Volumes.
Der Build kopiert nur die benötigten lokalen Quellen in einen temporären
Build-Kontext.

**Nur auf dem Host ausführen.** `scripts/agent-container` startet die
Docker-Sandbox von außen und braucht dafür Docker; der Container selbst
bekommt keinen Docker-Socket (siehe unten) und kann das Skript nicht
verwenden. Läuft eine Sitzung bereits innerhalb des Containers
(`KI_DEV_AGENT_CONTAINER=1`), das Zielkommando direkt ausführen, z. B.
`bd prime` oder `./.venv/bin/python -m pytest`, statt `scripts/agent-container`
erneut aufzurufen. Das Skript bricht in diesem Fall bewusst mit einem
Hinweis ab, statt Docker zu suchen.

Vom Repository aus (auf dem Host):

```bash
./scripts/agent-container build
./scripts/agent-container run loope doctor
./scripts/agent-container shell
```

Der Build verwendet die lokalen Quellen aus `../loope`; bei Bedarf:
`LOOPE_SOURCE=/pfad/zu/loope ./scripts/agent-container build`.
macOS-Binaries werden nicht kopiert. loope wird ohne TUI für Linux gebaut;
Codex und Claude Code werden über npm installiert. bd wird beim Image-Build
aus der über `BD_VERSION` festgelegten Go-Modulversion nativ nach
`/usr/local/bin/bd` installiert, mit CGO für Embedded Dolt und dem Build-Tag
`gms_pure_go`. Grundlage ist der
[Go-Installationsweg von Beads](https://github.com/gastownhall/beads/blob/main/.goreleaser.yml).
Das Dolt-CLI wird als Release-Binary nach `/usr/local/bin/dolt` gelegt
(Architektur über `TARGETARCH`, Fallback `dpkg --print-architecture`).
Alle Image-, Toolversionen und Go-Prüfsummen stehen ausschließlich in
`src/ki_dev/tool-versions.json`. Das Buildskript übergibt diese Werte als
Build-Argumente; Python-Code und Tests lesen dieselbe mitgelieferte Datei.
Der Host benötigt Python 3 mit `jsonschema`; bevorzugt wird `.venv/bin/python`,
sonst `python3`. Fehlende oder ungültige Werte brechen vor dem Build ab.
Versionswechsel separat committen, das Image neu bauen und die betroffenen
Tests ausführen. Es gibt keinen separat gepflegten verifizierten Versionsstand.

Paket-Downloads beim Image-Bau landen in BuildKit-Cache-Mounts, je
Paketverwalter einer (`id=npm`, `id=pip`, Go über seine Zielpfade). Sie
liegen im Builder, bei Colima also in der VM, und weder im Image noch im
laufenden Container. Anzeigen und begrenzen:
`docker buildx du --filter type=exec.cachemount`,
`docker buildx prune --filter type=exec.cachemount --keep-storage 5GB`.

## beads-Entwicklung unter `/beads`

Die Go-Version ist mit der `toolchain` aus `beads/go.mod` abzustimmen,
die golangci-lint-Version mit der beads-CI. Go wird per sha256 geprüft,
golangci-lint aus den Quellen gebaut. `GOTOOLCHAIN=local` verhindert Nachladen anderer Toolchains.
Modul- und Build-Cache liegen unter `/home/agent/go` bzw. `~/.cache/go-build`
im Home-Volume und bleiben zwischen Sitzungen erhalten.

Liegt `../beads` neben diesem Repo, bindet das Startskript es zusätzlich
über `compose.beads.yaml` schreibbar unter `/beads` ein. Von `/workspace`
aus funktioniert damit `cd ../beads`. Ein anderer Pfad:
`KI_DEV_AGENT_BEADS_REPO=/pfad/zu/beads ./scripts/agent-container shell`.

Für einen lokalen PR die Quellen **im Container** bauen und installieren:

```bash
cd /beads
source .buildflags
GOBIN="$HOME/go/bin" go install ./cmd/bd
hash -r
command -v bd  # /home/agent/go/bin/bd
cd /workspace
bd version
bd lint
```

`go build ./cmd/bd/...` allein installiert nichts. `~/go/bin` steht im
Container-PATH vor `/usr/local/bin`; ein dort installierter lokaler Build
wird damit auch von Agenten und Skripten als `bd` verwendet. Compose bindet
nur die Quellen ein und installiert beim Start keine Programme. Änderungen
im Checkout werden erst nach erneutem `go install` wirksam; das Image selbst
enthält weiterhin die festgelegte Release-Version, keine lokalen PR-Patches.

Der lokale Build bleibt im Home-Volume auch nach einem Image-Neubau erhalten.
Vor einem Wechsel zurück zu `/usr/local/bin/bd` prüfen, ob dessen Version
das aktuelle Datenbankschema unterstützt. Ein neuerer Entwicklungsstand kann
die Datenbank bereits migriert haben; eine Schemawarnung nicht umgehen.

## Weitere Nachbar-Repos per `--mount`

Weitere Nachbar-Repos werden je Aufruf gewählt, nach dem Muster von
`docker buildx build --platform a,b`: `-m`/`--mount` ist wiederholbar und
nimmt kommagetrennte Namen; eindeutige Präfixe genügen (wie bei
`getopt_long`). `NAME` wendet die Compose-Datei `NAME.yaml` aus dem
benutzereigenen Ordner an:

```text
${XDG_CONFIG_HOME:-~/.config}/ki-dev/agent-container/mounts/NAME.yaml
```

Welche Repos jemand einbindet, ist Benutzersache und steht deshalb nicht im
VCS. Der Ordner liegt außerhalb des Checkouts, damit neue Worktrees,
`git clean -fdX` und Neuklonen ihn nicht verlieren. Für eine neue Datei die
Vorlage kopieren und Name und Pfad ersetzen:

```bash
dir="${XDG_CONFIG_HOME:-$HOME/.config}/ki-dev/agent-container/mounts"
mkdir -p "$dir" && cp docker/agent/mount.example.yaml "$dir/mdman.yaml"
./scripts/agent-container mounts                 # Namen und Ziele
./scripts/agent-container -m mdman,mdman-ai shell
./scripts/agent-container --mount=lebens run ls /lebenslauf-web-vorlage
```

Quellpfade absolut angeben: Compose löst relative Pfade gegen den
ki-dev-Checkout auf, und der liegt je Worktree woanders. Unbekannte oder
mehrdeutige Namen brechen mit Exit 2 ab; fehlt ein gewähltes Repo, bricht
Compose ab. Erzeugte Ordner eines Repos können per `tmpfs` aus dem
Host-Checkout herausgehalten werden, siehe Vorlage.

## Anmeldung und Start

Die vorhandenen Verzeichnisse `~/.claude` und `~/.codex` werden schreibbar
nach `/home/agent/.claude` und `/home/agent/.codex` eingebunden. Damit können
die CLIs die Host-Anmeldung verwenden und ihre Tokens erneuern. Es werden keine
API-Key-Variablen weitergereicht. Falls vorhanden, wird `~/.claude.json`
zusätzlich schreibgeschützt eingebunden und einmalig ins Container-Home kopiert.
Bei einem anderen Benutzerverzeichnis:
`KI_DEV_AGENT_AUTH_HOME=/Users/name ./scripts/agent-container shell`.

```bash
./scripts/agent-container run codex login status
./scripts/agent-container run claude auth status
./scripts/agent-container run loope run --in-place --no-commit 'DEIN AUFTRAG'
```

Die Anmeldedaten müssen dateibasiert vorliegen: Ein macOS-Keychain-Eintrag allein
ist im Linux-Container nicht verfügbar. Falls nötig, im Container erneut anmelden.
Keine Schlüssel ins Image schreiben.

## Ausführung

- Das ganze Repo einschließlich `.beads` ist unter `/workspace` schreibbar.
- Home und Linux-`.venv` liegen in eigenen Volumes pro Repositorypfad.
  Die macOS-`.venv` wird überdeckt und nicht überschrieben.
- Der Container läuft als Benutzer mit UID/GID des Build-Benutzers.
- Python lädt über `PYTHONPATH=/workspace/src` den aktuellen Repo-Code.
  Bei geänderten Abhängigkeiten Image neu bauen und das zugehörige venv-Volume
  gezielt erneuern (Name mit `docker volume ls` ermitteln).
- loope setzt selbst Sandbox-/Berechtigungsflags. Die Container-Launcher
  ersetzen diese durch uneingeschränkte Ausführung **innerhalb des Containers**.
  Auch Reviewer haben damit Schreibzugriff; ihre fachliche Rolle bleibt im Prompt.
- Claude lädt ausschließlich eine pro Aufruf erzeugte Settings-Datei (siehe
  „Container-Konfiguration“). Andere Benutzer-/Projekt-Settings und deren
  Sperr-Hooks bleiben deaktiviert. CLAUDE.md und Projektdaten bleiben
  verfügbar. Codex-Hooks sind abgeschaltet;
  die Host-Verzeichnisse `~/.codex/rules` und `~/.claude/rules` sowie
  `/workspace/.claude` werden mit leeren tmpfs überdeckt.
  Die Host-Dateien bleiben unverändert.
  Beads-Kontext bei Bedarf über `bd prime` laden.
- Der Container bekommt keinen Docker-Socket. Vom Host-Home sind ausschließlich
  die beiden CLI-Verzeichnisse eingebunden (einschließlich ihrer Zugangsdaten)
  sowie optional die schreibgeschützte `~/.claude.json`. Netzwerk ist für
  Modellzugriff und Paketinstallation verfügbar. Er kann das gemountete Repo
  vollständig ändern oder löschen.

Die [Codex-Dokumentation](https://developers.openai.com/codex/security)
beschreibt diese Ausführung für Umgebungen mit externer Isolation.

## Container-Konfiguration

Die Konfiguration ist in vier Bereiche getrennt. A und B werden als
**Verzeichnisse** eingebunden, nicht als Einzeldateien: Ein Editor, der atomar
speichert (neue Datei, dann Umbenennen), ersetzt die Inode. Ein
Einzeldatei-Bind bliebe auf der alten, gelöschten Inode stehen
(„Settings file not found … (deleted)“); ein Verzeichnis-Bind zeigt die neue
Datei sofort.

| Bereich | Quelle (Host) | Im Container | Schreibrechte |
| --- | --- | --- | --- |
| A Ausführungsrichtlinie | `docker/agent-settings/access/policy.json` | `/opt/agent-settings/access/` | nur Host; im Container read-only, auch unter `/workspace/docker/agent-settings/access` |
| B Modellparameter | `docker/agent-settings/model/claude.json`, `codex.json` | `/opt/agent-settings/model/` | Host und Container (dieselben Dateien) |
| C Lokale Regeln | – | tmpfs über `~/.claude/rules`, `~/.codex/rules`, `/workspace/.claude` | nur flüchtig im Container |
| D Anmeldung | `~/.claude`, `~/.codex`, optional `~/.claude.json` | `/home/agent/…` | Host und Container (Token-Erneuerung) |

**A** enthält die festen Vorgaben, die der Launcher (`agent_cli.py`) auswertet:

- `claude.settings`: werden in die erzeugte Claude-Settings-Datei übernommen
  (`skipDangerousModePermissionPrompt`, `disableAllHooks`).
- `codex.config`: werden als `-c key=value` übergeben (`features.hooks=false`).
- Fest im Launcher: `--dangerously-skip-permissions` bzw.
  `--dangerously-bypass-approvals-and-sandbox`, `--setting-sources ""`, das
  Entfernen der loope-Sandbox-/Approval-Argumente (einschließlich
  `-c sandbox_mode=…`/`-c approval_policy=…` bei Codex).

Dass Agenten A weder lesen noch ändern, ist eine Arbeitsregel. Technisch
verhindert ist nur das Schreiben im Container (beide Pfade read-only); lesen
können Prozesse im Container die Datei. A enthält deshalb keine Geheimnisse.

**B** enthält ausschließlich diese Schlüssel; alles andere wird abgelehnt:

- Claude: `model`, `effortLevel` (`low`/`medium`/`high`/`xhigh`),
  `modelSettings.<modell>.effortLevel`, `advisorModel`, `language`.
  Alle Schlüssel sind im Schema von Claude Code 2.1.272 vorhanden.
  `language` (Antwortsprache) liegt bewusst in B: Die Einstellung betrifft nur
  die Modellausgabe, nicht die Ausführungsrichtlinie. `maxEffortLevel` ist
  nicht erlaubt, weil es explizite `--effort`-Werte des Aufrufers deckeln würde.
- Codex: `model`, `model_reasoning_effort`.

**D** bleibt außerhalb des Repositorys. Tokens gehören weder nach A noch nach B.

### Auswertung und Priorität

Bei jedem regulären `claude`-/`codex`-Aufruf liest und validiert der Launcher A
und B neu. Aufrufe zur Anmeldung und Diagnose (`auth`, `login`, `logout`,
`doctor`, `--help`, `--version`) werden unverändert durchgereicht und lesen A/B
nicht.

1. **A** gilt immer. B darf keine A-Schlüssel enthalten und umgekehrt.
   Aufrufer-Argumente, die A widersprechen, brechen mit Fehler ab: bei Claude
   `--settings` und `--setting-sources`, bei Codex `-c`/`--config` mit einem
   A-Schlüssel sowie `--enable`/`--disable` für ein Feature aus A.
2. **Explizite Aufruferwerte** schlagen B. Für jeden gesetzten Wert lässt der
   Launcher den entsprechenden B-Default weg, statt einen zweiten,
   widersprüchlichen Wert zu erzeugen:
   - Claude: `--model` ersetzt `model`; `--effort` ersetzt `effortLevel` und
     `modelSettings`.
   - Codex: `-m`/`--model` ersetzt `model`; `-c`/`--config` mit `model` oder
     `model_reasoning_effort` ersetzt den jeweiligen Wert; `-p`/`--profile`
     und `--oss` ersetzen beide Werte.
   - Erkannt werden die Formen `OPTION WERT` und `OPTION=WERT`.
3. **B** gilt für alle übrigen Werte.

Ungültiges oder fehlendes A/B (kein JSON, unbekannte Schlüssel, falsche Typen,
ungültiger Effort) bricht den Aufruf mit `agent-cli: <datei>: <grund>` ab.
Dann wird keine Konfiguration erzeugt oder verwendet.

- **Claude:** Der Launcher schreibt A+B pro Aufruf nach
  `/opt/agent-settings/generated/claude-<pid>-<zufall>.json` (erst temporär,
  dann atomar umbenannt) und startet `claude --setting-sources ""
  --settings <datei>`. `generated/` liegt nur im Container-Dateisystem, gehört
  dem Containerbenutzer (Modus 700) und hat keinen Host-Mount. Parallele
  Aufrufe erhalten getrennte Dateien. Dateien beendeter Aufrufe werden beim
  nächsten Aufruf entfernt; alle verschwinden mit dem Container.
- **Codex:** Keine erzeugte `config.toml`. A und B gehen als TOML-kodierte
  Overlays (`-c features.hooks=false -c model="…"`) vor die
  Aufruferargumente.
- Es wird nichts nach `~/.claude/settings.json` oder `~/.codex/config.toml`
  geschrieben; diese liegen im Host-Mount. Erzeugte Dateien werden nie nach B
  zurückgeschrieben. Dauerhafte Modelländerungen erfolgen in B.

### Wann Änderungen wirken

- **B ändern** (auf dem Host oder im Container): gilt beim nächsten
  `claude`-/`codex`-Aufruf, ohne Containerneustart oder Image-Rebuild. Bereits
  laufende Sitzungen laden B nicht nach.
- **A ändern**: auf dem Host bearbeiten; gilt ebenfalls beim nächsten Aufruf.
- **Einmalige Migration** (dieser Umbau, Änderungen an `agent_cli.py`,
  Dockerfile oder Mounts): Image neu bauen
  (`./scripts/agent-container build`) und laufende Container neu starten.

### Reichweite gegenüber ki-dev

`ki_dev.executors.contract.TurnRequest` verlangt `model` und `effort` ohne
Default. Der Claude-Adapter übergibt `--model` und `--effort`, der
Codex-Adapter `--model` und `-c model_reasoning_effort=…`. Nach Punkt 2 lässt
der Launcher deshalb die B-Werte für Modell und Effort bei automatisierten
ki-dev-Läufen immer weg (Test `test_ki_dev_turn_values_beat_defaults`).
**B ist kein Stellhebel für ki-dev-Läufe**; dort gelten die Werte aus dem
`TurnRequest`. B dient als Default für manuelle und interaktive Aufrufe
(z. B. `claude` in `./scripts/agent-container shell`). Übrige B-Werte wie
`language` oder `advisorModel` wirken auch bei ki-dev-Läufen mit Claude.

## Beads

Host und Container verwenden dieselbe Dolt-Datenbank. Keine gleichzeitigen
bd-Prozesse auf Host und Container betreiben; Lock-Dateien niemals löschen,
um einen aktiven Zugriff zu erzwingen. Bei laufenden Host-Agenten zunächst
deren bd-Aktivitäten beenden. Ein Lock-Fehler muss vor dem Agentenlauf geklärt sein.

```bash
./scripts/agent-container run bd --readonly list --limit 5
```

### Direkter Dolt-Zugriff

Das Dolt-CLI liegt im Image und arbeitet auf demselben Verzeichnis wie bd:
`/workspace/.beads/embeddeddolt/ki_dev_ablauf`. Dolt arbeitet relativ zum
aktuellen Verzeichnis, deshalb zuerst dorthin wechseln:

```bash
./scripts/agent-container run bash -lc 'cd /workspace/.beads/embeddeddolt/ki_dev_ablauf \
  && dolt sql -q "SHOW TABLES"'
```

Es läuft **kein** Dolt-Server als eigener Compose-Dienst. Das wäre ein zweiter
dauerhafter Schreiber auf derselben Datenbank; das CLI ist stattdessen ein
kurzlebiger Prozess, den der Bedienende steuert. Es gilt dieselbe Regel wie für
bd: nie gleichzeitig mit einem bd-Prozess auf Host oder Container schreiben.
Lesende Abfragen vor schreibenden bevorzugen und schreibende Änderungen mit
`dolt commit` abschließen, damit `bd` und die Referenzbildung in
`ki_dev.deltas.beads_changes` einen sauberen Dolt-Commit sehen.

Die Identität für `dolt commit` setzt `entrypoint.sh` im Home-Volume, je
Schlüssel nur solange er leer ist (Vorgaben `agent` /
`agent@ki-dev-ablauf.invalid`). Andere Werte über `DOLT_USER_NAME` und
`DOLT_USER_EMAIL` setzen oder im Container einmalig
`dolt config --global --add user.name …` aufrufen; ein so gesetzter Wert bleibt
erhalten und wird nicht wieder überschrieben.

Die Container-Einrichtung ändert weder die fachliche Bestätigungspflicht
eines Auftrags noch das loope-Iterationslimit.
