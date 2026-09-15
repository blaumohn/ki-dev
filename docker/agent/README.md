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
bd 1.2.2, Codex 0.154.0 und Claude Code 2.1.272 werden über npm installiert.
Versionsänderungen erfolgen über die ARG-Vorgaben im Dockerfile.

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
- Claude lädt ausschließlich `docker/claude-settings.json`, das im Container
  unter `/home/agent/.claude/settings.json` liegt. Andere Benutzer-/Projekt-Settings
  und deren Sperr-Hooks bleiben deaktiviert. CLAUDE.md und Projektdaten bleiben
  verfügbar. Codex-Hooks sind abgeschaltet;
  das Host-Verzeichnis `~/.codex/rules` wird mit einem leeren tmpfs überdeckt.
  Die Host-Dateien bleiben unverändert.
  Beads-Kontext bei Bedarf über `bd prime` laden.
- Der Container bekommt keinen Docker-Socket. Vom Host-Home sind ausschließlich
  die beiden CLI-Verzeichnisse eingebunden (einschließlich ihrer Zugangsdaten)
  sowie optional die schreibgeschützte `~/.claude.json`. Netzwerk ist für
  Modellzugriff und Paketinstallation verfügbar. Er kann das gemountete Repo
  vollständig ändern oder löschen.

Die [Codex-Dokumentation](https://developers.openai.com/codex/security)
beschreibt diese Ausführung für Umgebungen mit externer Isolation.

## Beads

Host und Container verwenden dieselbe Dolt-Datenbank. Keine gleichzeitigen
bd-Prozesse auf Host und Container betreiben; Lock-Dateien niemals löschen,
um einen aktiven Zugriff zu erzwingen. Bei laufenden Host-Agenten zunächst
deren bd-Aktivitäten beenden. Ein Lock-Fehler muss vor dem Agentenlauf geklärt sein.

```bash
./scripts/agent-container run bd --readonly list --limit 5
```

Die Container-Einrichtung ändert weder die fachliche Bestätigungspflicht
eines Auftrags noch das loope-Iterationslimit.
