# Agenten im Docker-Container

Die Laufzeitkonfiguration steht zentral in `compose.yaml`. Das Startskript
ruft Docker Compose auf und behält pro Repo dieselben Home-/venv-Volumes
(Dev-Modus); `--fresh` startet stattdessen eine temporäre Test-Instanz,
siehe „Dev- und Testmodus“.
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
./scripts/agent-container run bd version
./scripts/agent-container shell
```

Codex und Claude Code werden über npm installiert, ki-dev aus den
Projektquellen in die Image-venv. Antigravity CLI (`agy`) wird als natives
Linux-Release für amd64 oder arm64 nach `/usr/local/bin/agy` installiert.
Version, Download-URLs und SHA512-Prüfsummen sind ebenfalls in der gemeinsamen
Versionsdatei festgeschrieben; die Downloads stammen aus den Manifesten des
[offiziellen Installers](https://antigravity.google/cli/install.sh).
bd wird beim Image-Build
aus der über `BD_VERSION` festgelegten Go-Modulversion nativ nach
`/usr/local/bin/bd` installiert, mit CGO für Embedded Dolt und dem Build-Tag
`gms_pure_go`. Grundlage ist der
[Go-Installationsweg von Beads](https://github.com/gastownhall/beads/blob/main/.goreleaser.yml).
Das Dolt-CLI wird als Release-Binary nach `/usr/local/bin/dolt` gelegt
(Architektur über `TARGETARCH`, Fallback `dpkg --print-architecture`).
Alle Image-, Toolversionen, Download-URLs und Prüfsummen stehen ausschließlich in
`src/ki_dev/tool-versions.json`. Das Buildskript übergibt diese Werte als
Build-Argumente; Python-Code und Tests lesen dieselbe mitgelieferte Datei.
Der Host benötigt Python 3 mit `jsonschema`, für `--mount` zusätzlich
`plumbum`; bevorzugt wird `.venv/bin/python`, sonst `python3`. Fehlende oder ungültige Werte brechen vor dem Build ab.
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
Modul- und Build-Cache (`~/go/pkg/mod`, `~/.cache/go-build`) liegen als
Host-Ordner unter `${XDG_CACHE_HOME:-~/.cache}/agent-container`, siehe
„Dev- und Testmodus“.

Liegt `../beads` neben diesem Repo, bindet das Startskript es zusätzlich
über `compose.beads.yaml` schreibbar unter `/beads` ein. Von `/workspace`
aus funktioniert damit `cd ../beads`. Ein anderer Pfad:
`KI_DEV_AGENT_BEADS_REPO=/pfad/zu/beads ./scripts/agent-container shell`.

Für einen lokalen PR die Quellen **im Container** bauen:

```bash
cd /beads
source .buildflags
go build -o .build/linux/bd ./cmd/bd
hash -r
command -v bd  # /beads/.build/linux/bd
cd /workspace
bd version
bd lint
```

Der Dev-Build liegt im beads-Checkout unter `.build/linux/bd`, nicht im
Home. `compose.beads.yaml` setzt `/beads/.build/linux` im PATH direkt hinter
`/opt/agent-bin`, also vor `/usr/local/bin` und `~/go/bin`; Agenten und
Skripte verwenden damit den lokalen Build als `bd`. Der PATH wiederholt
sonst den Image-PATH aus dem Dockerfile; ein Test hält beide gleich. Login-
Shells (`bash -lc`, so ruft Codex Befehle auf) setzt `/etc/profile` den PATH
zurück; der Entrypoint sichert ihn daher als `KI_DEV_AGENT_PATH`, und
`/etc/profile.d/ki-dev-agent-path.sh` stellt ihn wieder her. Das
Startskript trägt `.build/` in die `info/exclude` des beads-Checkouts ein
(auch bei einem Worktree), damit `git status` dort sauber bleibt. Compose
bindet nur die Quellen ein und baut beim Start nichts. Änderungen im
Checkout werden erst nach erneutem `go build` wirksam; das Image selbst
enthält weiterhin die festgelegte Release-Version, keine lokalen PR-Patches.
Ohne `.build/linux/bd` gilt wieder `/usr/local/bin/bd`. Nutzt
`.beads/config.yaml` dieses Repos `lint.max-chars` (nur im lokalen Build,
ki-dev-ablauf-qdg), bricht das Startskript stattdessen mit Exit 1 ab, wenn
der Checkout oder `.build/linux/bd` fehlt; ob der Build aktuell ist, prüft es
nicht. Die bd-Warnung
„multiple 'bd' binaries found in PATH“ ist dabei erwartet: Sie nennt den
Dev-Build als verwendet.

Gemessen am 01.10. (go-build als Host-Ordner): erster Build kalt einschließlich
Modul-Download 147 s, danach mit warmem Cache 3 s und 2 s.

Der lokale Build bleibt im Checkout auch nach einem Image-Neubau erhalten.
Vor einem Wechsel zurück zu `/usr/local/bin/bd` prüfen, ob dessen Version
das aktuelle Datenbankschema unterstützt. Ein neuerer Entwicklungsstand kann
die Datenbank bereits migriert haben; eine Schemawarnung nicht umgehen.

## Referenzordner schreibgeschützt einbinden

Mit `--mount-ro PFAD` lassen sich vorhandene Ordner direkt zum Lesen
einbinden. Die Option ist für mehrere Ordner wiederholbar:

```bash
./scripts/agent-container --mount-ro ../beispiel-repo --mount-ro /pfad/zu/doku shell
./scripts/agent-container --mount-ro=../beispiel-repo run ls /references/beispiel-repo
```

Jeder Ordner erscheint schreibgeschützt unter `/references/<Ordnername>`.
Relative Pfade beziehen sich auf das aktuelle Host-Verzeichnis; Pfade mit
Leerzeichen in Anführungszeichen setzen. Symlinks werden aufgelöst; der
Name des Zielordners bestimmt den Container-Pfad. Unterschiedliche Ordner
mit demselben Namen werden abgelehnt, wiederholte identische Pfade nur
einmal eingebunden. Fehlende Ordner, `/` und Pfade mit Doppelpunkt werden
abgelehnt.

Es braucht keine YAML-Datei; für diese Ordner werden keine Abhängigkeiten
installiert und keine Builds gestartet. Die Option gilt für `shell` und
`run` und lässt sich mit `--mount` und `--fresh` kombinieren. Ein bereits
vorhandenes Agent-Image genügt, ein Image-Neubau ist dafür nicht nötig.

## Ablaufpakete (`KI_DEV_FLOW_PATH`)

Ablaufpakete außerhalb des Gerüsts (Ablauf, Ops, Vorlagen, Profile)
findet `ki-dev -f NAME` über `KI_DEV_FLOW_PATH`. Compose setzt die
Variable im Container aus `KI_DEV_AGENT_FLOW_PATH` des Hosts; der Wert
ist ein Pfad im Container-Namensraum, Standard
`/workspace/.local/ablaufpakete`. Das Verzeichnis liegt im eingebundenen
Repo und gehört der Agent-UID (Host-UID), der Agent kann dort Dateien
anlegen und ändern; einen zusätzlichen Mount braucht es nicht.

```bash
KI_DEV_AGENT_FLOW_PATH=/workspace/ablaufpakete ./scripts/agent-container shell
KI_DEV_AGENT_FLOW_PATH= ./scripts/agent-container shell   # ohne Suchpfad
```

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
./scripts/agent-container mounts                 # Namen, Ziele, Quellen
./scripts/agent-container -m mdman,mdman-ai shell
./scripts/agent-container --mount=lebens run ls /lebenslauf-web-vorlage
```

`mounts` zeigt je Datei das erste `target:` und `source:` und meldet einen
fehlenden oder leeren Ordner ausdrücklich.
Quellpfade absolut angeben: Compose löst relative Pfade gegen den
ki-dev-Checkout auf, und der liegt je Worktree woanders. Unbekannte oder
mehrdeutige Namen brechen mit Exit 2 ab; fehlt ein gewähltes Repo, bricht
Compose ab. Erzeugte Ordner eines Repos können per `tmpfs` aus dem
Host-Checkout herausgehalten werden, siehe Vorlage.

### Repo-Vertrag `x-ki-dev`

Eine Mount-Datei darf zusätzlich beschreiben, welche Paketverwalter das
eingebundene Repo nutzt, aus welchen Eingabedateien sie installieren und
wohin. Das Compose-Erweiterungsfeld steht neben der Einbindung; Compose selbst
ignoriert es:

```yaml
x-ki-dev:
  repo: /lebenslauf-web-vorlage   # Container-Pfad, ein target dieser Datei
  deps:
    - {manager: npm,      inputs: [package.json, package-lock.json], install: node_modules}
    - {manager: composer, inputs: [composer.json, composer.lock],    install: vendor}
```

Fehlt `x-ki-dev`, bleibt es beim reinen Einbinden. Ein vorhandener Vertrag
wird vor jedem `shell`/`run` geprüft; ist er ungültig, bricht das Skript mit
Exit 2 ab, bevor Docker startet. Die Meldung nennt Datei und Feldpfad, etwa
`lebens.yaml: x-ki-dev.deps.0.manager: unbekannter Wert`. Geprüft werden:
bekannter `manager` (`npm`, `composer`), nichtleere `inputs`, die im Repo
vorhanden sind, `install` und `inputs` relativ und innerhalb von `repo`,
kein doppelter `install`-Pfad, `repo` ist ein Bind-`target` der Datei.

Zuständig ist `src/ki_dev/agent_repo_contract.py` (JSON Schema plus benannte
Prüfungen). Die YAML-Datei liest `docker compose config`; der Vertrag sieht
damit dieselbe Syntax, Interpolation und Pfadauflösung wie der echte Lauf,
ohne eigene YAML-Bibliothek. Von Hand:

```bash
PYTHONPATH=src ./.venv/bin/python -m ki_dev.agent_repo_contract \
  --project-directory . "$dir/lebens.yaml"
```

Die Ausgabe ist der normalisierte Vertrag als JSON. Mit `--agent` sind
höchstens ein Repo mit `deps` erlaubt, sonst Exit 2; das Skript verwendet
diesen Modus erst mit `--agent` (ki-dev-ablauf-d51). Der Dateiname ohne
`.yaml` ist der Repo-Name; Volumes und Images aus einem Vertrag tragen
das Label `ki-dev.repo=<NAME>`; für npm-Verzeichnisse siehe
„Dev- und Testmodus“.

## Dev- und Testmodus

| | Dev (Standard) | Test (`--fresh`) |
| --- | --- | --- |
| Home `/home/agent` | Volume `ki-dev-agent-<key>-home` | anonymes Volume |
| `/workspace/.venv` | Volume `ki-dev-agent-<key>-venv` | anonymes Volume, frisch aus dem Image |
| npm-`install` aus `x-ki-dev` | Volume `ki-dev-repo-<NAME>-<install>-<hash>` | tmpfs |
| `~/.cache/go-build` | Host-Ordner `go-build` | anonymes Volume |
| `~/.npm`, `~/.cache/pip`, `~/go/pkg/mod` | Host-Ordner, geteilt | Host-Ordner, geteilt |

`<key>` ist eine Prüfsumme des Checkout-Pfads, je Worktree also eigene
Volumes. Der Dev-Modus verhält sich wie eine lokale Entwicklungsumgebung:
Home, venv und `node_modules` bleiben zwischen Läufen erhalten. Mit
`--fresh` läuft der Container wie in der CI; alles außer den Download-Caches
ist temporär und verschwindet mit dem Container (`run --rm`). Der lokale
go-build-Ordner bleibt dabei unberührt.

```bash
./scripts/agent-container --fresh -m lebens run bash -c 'cd /lebenslauf-web-vorlage && npm ci'
./scripts/agent-container -m lebens reset
```

**Download-Caches** (npm, pip, go mod) liegen als Host-Ordner unter
`${XDG_CACHE_HOME:-~/.cache}/agent-container/` und werden über alle Repos,
Checkouts und beide Modi geteilt. Das Skript legt sie vor dem Start an
(sonst legte Docker sie als root an). Daneben liegt `go-build`, der erzeugte
Go-Build-/Testcache des Dev-Modus, und `compose/` mit den je Lauf erzeugten
Compose-Dateien für `node_modules` (`deps-<PID>.json`; Dateien beendeter
Läufe entfernt der nächste Start).

**node_modules fremder Repos:** Für jeden npm-Eintrag eines Repo-Vertrags
(`x-ki-dev`) hängt im Dev-Modus ein Named Volume über
`<repo>/<install>`, mit Label `ki-dev.repo=<NAME>`. Der Hash über Name und
`install` trennt Pfade mit gleichem lesbarem Teil (`packages/ui` und
`packages-ui`). Das Volume ist Linux-eigen,
der Mac-Stand im Checkout bleibt unberührt. npm erkennt geänderte Lockfiles
über `node_modules/.package-lock.json`. Damit das Volume beim Anlegen nicht
root gehört, hängt es zusätzlich an einem leeren, agent-eigenen Platz
`/opt/agent-volume-seed/<n>` des Images; Docker übernimmt dessen Besitzer.
Es gibt 8 Plätze, also höchstens 8 solche Verzeichnisse je Lauf. Im
Testmodus ist das Verzeichnis ein tmpfs mit dem Container-Benutzer als
Eigentümer (69–295 MB je Repo gemessen); `npm ci` installiert frisch aus
dem geteilten Cache.

**reset** entfernt die Home- und venv-Volumes dieses Checkouts sowie mit
`-m NAME` die Volumes mit Label `ki-dev.repo=NAME`; Download-Caches und
go-build bleiben. Anlass: Drift im Home (etwa `pip --user`-Pakete) oder eine
veraltete venv nach einem Image-Neubau. Fehlende Volumes werden übersprungen;
läuft noch ein Container, bricht `reset` mit Hinweis ab.

`~/.claude.json` kopiert der Entrypoint nur, wenn sie im Home fehlt; mit
`--fresh` also bei jedem Start frisch vom Host.

## Anmeldung und Start

Die vorhandenen Verzeichnisse `~/.claude`, `~/.codex` und `~/.gemini` werden
schreibbar nach `/home/agent/.claude`, `/home/agent/.codex` und
`/home/agent/.gemini` eingebunden. Alle drei müssen auf dem Host vorhanden sein.
Damit können
die CLIs die Host-Anmeldung verwenden und ihre Tokens erneuern. Es werden keine
API-Key-Variablen weitergereicht. Falls vorhanden, wird `~/.claude.json`
zusätzlich schreibgeschützt eingebunden und einmalig ins Container-Home kopiert.
Bei einem anderen Benutzerverzeichnis:
`KI_DEV_AGENT_AUTH_HOME=/Users/name ./scripts/agent-container shell`.

Auch die agy-Anmeldung bleibt durch den Host-Mount bei Container-Neustarts,
`--fresh` und `reset` erhalten. Die OAuth-Datei
`~/.gemini/antigravity-cli/antigravity-oauth-token` bleibt auf dem Host;
Token-Erneuerungen des Containers werden in dasselbe Verzeichnis geschrieben.
`KI_DEV_AGENT_AUTH_HOME` gilt für alle drei Anmeldeverzeichnisse.
Nach dem Image-Build startet `./scripts/agent-container run agy` die CLI direkt.

Die agy-Konfiguration liegt unter
[`~/.gemini/antigravity-cli/settings.json`](https://antigravity.google/docs/cli/using).
agy läuft direkt mit seiner eigenen Konfiguration; die nachfolgend beschriebenen
A/B-Launcher gelten für Codex und Claude. Der Mount stellt keine macOS-Keychain
im Container bereit und garantiert daher keine übertragbare Anmeldung.

```bash
./scripts/agent-container run agy --help
./scripts/agent-container run codex login status
./scripts/agent-container run claude auth status
./scripts/agent-container run ki-dev --help
```

Die Anmeldedaten müssen dateibasiert vorliegen: Ein macOS-Keychain-Eintrag allein
ist im Linux-Container nicht verfügbar. Falls nötig, im Container erneut anmelden.
Keine Schlüssel ins Image schreiben.

## Ausführung

- Das ganze Repo einschließlich `.beads` ist unter `/workspace` schreibbar.
- Home und Linux-`.venv` liegen im Dev-Modus in eigenen Volumes pro
  Repositorypfad (siehe „Dev- und Testmodus“).
  Die macOS-`.venv` wird überdeckt und nicht überschrieben.
- Der Container läuft als Benutzer mit UID/GID des Build-Benutzers.
- Python lädt über `PYTHONPATH=/workspace/src` den aktuellen Repo-Code.
  Bei geänderten Abhängigkeiten Image neu bauen und die Dev-Volumes mit
  `./scripts/agent-container reset` erneuern.
- loope setzt selbst Sandbox-/Berechtigungsflags. Die Container-Launcher
  ersetzen diese durch uneingeschränkte Ausführung **innerhalb des Containers**.
  Auch Reviewer haben damit Schreibzugriff; ihre fachliche Rolle bleibt im Prompt.
- Claude lädt ausschließlich eine pro Aufruf erzeugte Settings-Datei (siehe
  „Container-Konfiguration“). Andere Benutzer-/Projekt-Settings und deren
  Sperr-Hooks bleiben deaktiviert. CLAUDE.md (im Repository leer; den
  Einstiegskontext liefert `ki-dev step`) und Projektdaten bleiben
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

`ki_dev.adapter.executors.contract.TurnRequest` verlangt `model` und `effort` ohne
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

### Beads-Journal

Das Journal ist ein lokales Git-Repo, in dem jede Beads-Änderung als
eigener Commit landet. So lässt sich der Projektverlauf ohne Dolt lesen.
Die versionierten bd-Hooks `.beads/hooks/on_create`, `on_update` und
`on_close` rufen dafür `python -m ki_dev.beads_journal hook` auf. Danach
steht in `issues/<ID>.json` die letzte Nutzlast des Vorgangs. Die
Commit-Nachricht lautet `<Ereignis> <ID>: <Titel> [<Status>]`;
Zeilenumbrüche in Titel und Status werden dort zu Leerzeichen. Updates
lösen auch Labels, Abhängigkeiten, Kommentare und Typwechsel aus.

Einrichtung, einmal je Klon, auf dem Host oder im Container:

```bash
./.venv/bin/python -m ki_dev.beads_journal init      # oder: init --path P
./.venv/bin/python -m ki_dev.beads_journal status
```

`init` füllt das Journal einmalig aus `bd export` (ohne Memories) in
einem einzigen Commit; auf einem bestehenden Journal arbeitet es nur die
Warteschlange ab. Der Ort steht in `git config ki-dev.beadsJournal`.
Ohne Angabe gilt `.local/beads-journal`. Ein Ort im Repo wird relativ
gespeichert und gilt so auf dem Host und unter `/workspace`
gleichermaßen; ein Ort außerhalb ist im Container nicht eingebunden. Fehlt der Marker `.beads-journal`, endet der
Hook ohne Wirkung; ein Klon ohne Journal bleibt also unberührt.
Für Commits übernimmt das Journal `user.name` und `user.email` des
Projekt-Repos. Eigene Zusätze gehören in ein ausführbares
`.beads/hooks/on_<ereignis>.local`, das dieselben Argumente und dieselbe
stdin erhält. Voraussetzung ist git >= 2.32 (`commit --trailer`).

Wiederanlauf: Jeder Hook legt sein Ereignis zuerst in die Warteschlange
`<journal>/.queue.db` (persist-queue) und arbeitet sie dann unter der
Sperre ab, bis sie leer ist. Jeder Commit trägt den Trailer
`Journal-Event: <Queue-ID>`. Wird ein Hook zwischen Commit und
Bestätigung getötet, erkennt der nächste Lauf den Commit am Trailer und
committet nicht doppelt. Stirbt er während git schreibt, entfernt der
nächste Lauf die verwaisten Sperrdateien (`.git/index.lock`,
`.git/HEAD.lock`, `.git/packed-refs.lock`, `.git/refs/**/*.lock`) und
committet das Ereignis genau einmal. Automatische git-Wartung
(`gc --auto`, `maintenance run --auto`) ist für Journal-Commits
abgeschaltet: Sie liefe losgelöst weiter, und der Wiederanlauf hielte
ihre aktive Sperre für verwaist. Lose Objekte sammeln sich deshalb an;
`git gc` im Journal nur ausführen, wenn keine Hooks laufen können. Ist die Sperre 5 s belegt, bleibt das Ereignis liegen;
der Halter oder der nächste Hook committet es.

```bash
./.venv/bin/python -m ki_dev.beads_journal status   # arbeitet zuerst ab
./.venv/bin/python -m ki_dev.beads_journal drain    # nur abarbeiten
```

`status` zeigt zusätzlich `Warteschlange: N offen` und
`Fehlgeschlagen: N` mit je einer Zeile `#<Queue-ID> <Ereignis> <ID>:
<Grund>`. Dieselbe `#<Queue-ID>` steht in `.errors.log`.

```bash
cd .local/beads-journal
jq -r 'select(.status != "closed") | [.id, .status, .title] | @tsv' issues/*.json
git log -p -- issues/<ID>.json
```

Grenzen:

- Löschungen erzeugen kein Ereignis. Kommentartexte fehlen in der Nutzlast.
- bd startet Hooks asynchron mit 10 s Frist. Die Commits folgen der
  Eingangsreihenfolge der Warteschlange, nicht garantiert der
  Ereignisfolge. Trifft eine ältere Nutzlast verspätet ein, überschreibt
  sie die Datei nicht. Sie ergibt einen leeren Commit mit dem Vermerk
  ` (verspätet)`.
  Verglichen wird `updated_at` in ganzen Sekunden, Bruchteile werden
  abgeschnitten: bd liefert sie nur bei create, danach die Sekunde aus
  der DB. Innerhalb derselben Sekunde entscheidet die Reihenfolge der
  Warteschlange; Vertauschungen dort bleiben unerkannt (akzeptierte
  Präzisionsgrenze).
- Ungültige Nutzlast wird als fehlgeschlagen vermerkt, mit Feldpfad und
  ohne Rohwerte. Ein git-Fehler lässt das Ereignis in der Warteschlange;
  der nächste Lauf versucht es erneut. Gründe stehen in
  `<journal>/.errors.log`.
- `.queue.db` gehört zum Journal. Wer sie löscht, verliert offene
  Einträge, und neue Queue-IDs gelten fälschlich als schon committet.
- Die Sperre ist ein `flock`. Zwischen Host und Container über
  virtiofs ist sie unzuverlässig. Deshalb gilt auch hier: keine
  gleichzeitigen bd-Prozesse auf Host und Container (siehe oben).
- persist-queue betreibt die Warteschlange fest im WAL-Modus. Nach einem
  Abbruch bleiben `.queue.db-wal` und `.queue.db-shm` liegen. Ob ein
  anschließender Wechsel zwischen Host und Container über virtiofs
  sauber weiterläuft, ist noch ungeprüft (offenes Prüfrisiko).
- Ins Journal schreibt nur dieses Werkzeug. Solange Hooks laufen können,
  dort kein manuelles `git commit`, `reset` o. Ä. ausführen.
- Abhängigkeiten sind `filelock` und `persist-queue`. Das Host-venv
  braucht dafür `./.venv/bin/pip install -e .`. Für den Container ist
  ein Rebuild nötig (`./scripts/agent-container build`), danach die
  veraltete venv per `reset` erneuern (siehe oben). Fehlt eine davon,
  scheitert der Hook; bd verwirft den Fehler stillschweigend.
- Ein vor dem Wiederanlauf angelegtes Journal führt `.queue.db*` nicht
  in seiner `.gitignore`; `git status` zeigt die Dateien dort als
  ungetrackt. Das stört die Hooks nicht (sie stagen gezielt).

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
