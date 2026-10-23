Deutsch · [English](README.en.md)

# ki-dev

**Ein Python-Kommandozeilenprogramm für Arbeitsabläufe mit KI-Agenten.**
Du legst in TOML fest, wer arbeitet, wer prüft und wann ein Mensch
entscheidet. ki-dev führt die Schritte in einem Git-Repository aus.

## Inhalt

- [Minimalbeispiel: eine Codeänderung mit Review](#minimalbeispiel)
- [Ausprobieren: das Beispiel mit echten Agenten ausführen](#ausprobieren)
- [Stand: was läuft, was fehlt](#stand)
- [Weiterbauen: eigene Abläufe und nächste Arbeiten](#weiterbauen)
- [Mitmachen: beitragen und Änderungen prüfen](#mitmachen)
- [Lizenz](#lizenz)

## Minimalbeispiel

**Der Ablauf:** `implement` ist ein mitgelieferter Ablauf für Codeänderungen.
Er verbindet Umsetzung, Tests, Review und Korrektur. Welche Änderung
ansteht, beschreibt ein Auftrag in [Beads](https://github.com/steveyegge/beads).

**Der Beispielauftrag:** `add(a, b)` berechnet `a - b`; verlangt ist `a + b`.

**Die Besetzung:** `worker` und `review` sind die Rollen dieses Ablaufs.
Das Profil, eine TOML-Datei ([Schritt 3](#3-profil-speichern)), besetzt
sie mit Codex und Claude Code; ki-dev legt für jede Rolle eine eigene
Sitzung an.

Ein Lauf geht so:

1. Der Umsetzer (`worker`) bearbeitet den Auftrag.
2. ki-dev führt die Tests aus dem Profil aus.
3. Das Review erhält Änderung und Testergebnis und antwortet.
4. Die Antwort bestimmt, welcher festgelegte Übergang folgt:

| Review-Antwort | Reaktion von ki-dev |
|---|---|
| `fix` | Befund zur Korrektur an den Umsetzer; nach verbrauchten Korrekturrunden Halt für den Menschen. |
| `PASS` | Abschluss-Commit vorbereiten und per Fast-Forward in den Zielbranch übernehmen. |
| `decision` | Für eine menschliche Entscheidung anhalten. |

Die Übergänge stehen in [TOML](docs/vertiefung.de.md#ablaufregeln),
Python führt sie aus. Das Profil besetzt die Rollen und setzt Grenzen;
der Auftrag liefert Inhalt und Abnahmekriterien.

> **Prototyp:** Mit echten Agenten erprobt ist bisher dieser eine Auftrag
> ([Ergebnis](#5-ergebnis-ansehen)). Rote Tests blockieren die Übernahme
> noch nicht automatisch. [Stand und Grenzen](#stand)

## Ausprobieren

Die fünf Schritte laufen nacheinander im selben Terminal. Du brauchst:

- **ki-dev:** Python ≥ 3.12 mit `venv` und `pip`, Git ≥ 2.32.
- **Aufträge:** Beads (`bd`). `make setup` baut die
  [festgelegte Version](src/ki_dev/tool-versions.json) mit Bash, Make, Go
  und einem C-Compiler; Go und C braucht nur dieser Bau.
- **Agenten:** [Codex CLI](https://github.com/openai/codex) und
  [Claude Code](https://code.claude.com/docs), beide angemeldet. Der Lauf
  ruft echte Modelle auf und verbraucht Tokens; das Profil wählt je CLI
  das günstigste Modell mit Effort `low`. Ohne Modellzugang führt
  `make demo` denselben Ablauf mit vorgegebenen Antworten vor
  ([Demo](docs/vertiefung.de.md#demo-ohne-modellzugang)).

### 1. Einrichten

<!-- readme-script: readme-scripts/1-setup.sh -->
Der erste Lauf braucht Netz und wegen des Beads-Baus einige Minuten.

```bash
git clone https://github.com/blaumohn/ki-dev.git ki-dev
cd ki-dev
make setup                          # venv mit ki-dev und bd
export PATH="$PWD/.venv/bin:$PATH"  # ki-dev und bd im PATH
```

> ✅ Im leeren Container ausgeführt · [Test](tests/readme/test_1_setup.sh)
<!-- /readme-script -->

### 2. Auftrag anlegen

<!-- readme-script: readme-scripts/3-auftrag.sh -->
Im selben Terminal wie die Einrichtung. Die Befehle legen ein
Wegwerf-Repo mit dem Fehler an: `calc` trägt den Zielbranch `main`,
im Worktree `calc-work` arbeiten die Agenten. `bd create` speichert
Problem, Entwurf und Abnahmekriterien als Auftrag; `implement` liest
diese Felder.

```bash
cd "$(mktemp -d)"
git init -q -b main calc && cd calc  # Wegwerf-Repo
git config user.name calc  # Identität nur für dieses Wegwerf-Repo
git config user.email calc@example.invalid
cat >add.py <<'EOF'
def add(a, b):
    return a - b
EOF
cat >test_add.py <<'EOF'
from add import add

assert add(2, 3) == 5
EOF
printf '%s\n' .ki-dev/ .beads.gate.lock __pycache__/ \
  >>.git/info/exclude  # Laufdaten, Python-Cache
git add . && git commit -q -m "add()"
git worktree add -q -b work ../calc-work  # Arbeits-Worktree der Agenten
cd ../calc-work
bd init --quiet --prefix calc --stealth --non-interactive
BEAD="$(bd create "add() does not add" \
  --description "add(2, 3) returns -1" \
  --design "fix add.py; do not change test_add.py" \
  --acceptance "add(2, 3) == 5 and add(-1, 1) == 0" \
  --silent)"
echo "$BEAD"
```

> ✅ Im leeren Container ausgeführt · [Test](tests/readme/test_3_auftrag.sh)

`$BEAD` ist die ID des Auftrags, etwa `calc-7k2`.
<!-- /readme-script -->

### 3. Profil speichern

<!-- readme-script: readme-scripts/4-rollen.sh -->
Das Profil besetzt die Rollen: Codex setzt um, Claude Code prüft.
Beide nutzen das günstigste Modell ihrer CLI mit Effort `low`; ki-dev
legt für jede Rolle beim ersten Aufruf eine eigene Sitzung an.
Weiter in `calc-work`:

```bash
mkdir -p .ki-dev/profiles       # ki-dev sucht Profile im Startordner
cat >.ki-dev/profiles/default.toml <<'EOF'
workdir = "."                   # Arbeits-Worktree, hier startet ki-dev
access_profile = "write"        # der Umsetzer darf hier schreiben

[worker]                        # setzt um
executor = "codex"
model = "gpt-6-luna"
effort = "low"

[review]                        # prüft, nur lesend
executor = "claude"
model = "haiku"
effort = "low"

[[tests]]                       # läuft je Runde, Ergebnis ans Review
name = "test_add"
argv = ["python3", "test_add.py"]

[limits]
changes_rounds = 3              # höchstens drei Korrekturrunden

[finalization]                  # wohin ein akzeptiertes Ergebnis geht
target_workdir = "../calc"      # Ziel-Repo mit Branch main
target_ref = "refs/heads/main"
commit_message = "Fix add()"
EOF
```

> ✅ Im leeren Container ausgeführt · [Test](tests/readme/test_4_rollen.sh)

- `executor` lässt sich je Rolle austauschen; vorhanden sind `codex`,
  `claude`, `mock` und `manual` ([Executoren](docs/ausfuehrer.de.md#executoren)).
- Grenzen je Aufruf (Zeit, Kosten, Kontingent) haben
  [Standardwerte](docs/ausfuehrer.de.md#verbrauchsschutz).
<!-- /readme-script -->

### 4. Starten

<!-- readme-script: readme-scripts/5-starten.sh -->
Weiter in `calc-work`. ki-dev ruft jetzt die Agenten auf; je nach
Modell dauert das Sekunden bis Minuten. Mit `-v` zeigt ki-dev
Zustandswechsel und Agentenausgabe live.

```bash
ki-dev -f implement "$BEAD" --run-id add-fix  # Profil default
```

> ⏳ Ungeprüft: der erste Agentenaufruf braucht angemeldete Agenten-CLIs; bis dahin ausgeführt · [Test](tests/readme/test_5_starten.sh)

Am Ende steht der Endzustand als JSON, nach Erfolg mit
`"status": "passed"`. Hält der Lauf an, nennt `detail` den Grund;
`ki-dev -f implement resume add-fix` setzt danach fort
([Halt und Fortsetzen](docs/ausfuehrer.de.md)).
<!-- /readme-script -->

### 5. Ergebnis ansehen

<!-- readme-script: readme-scripts/9-ergebnis.sh -->
Weiter in `calc-work`. `history` fasst den Lauf aus seinen
gespeicherten Zwischenständen zusammen; den Abschluss-Commit trägt das
Ziel-Repo `calc`.

```bash
ki-dev -f implement history add-fix  # Runden, Tests, Review, Abschluss
git -C ../calc log -1 --format=%s    # Abschluss-Commit auf main
git -C ../calc show main:add.py      # korrigierte Datei auf main
```

> ✅ Mit echten Agenten ausgeführt · [Test](tests/readme/test_9_ergebnis.sh)

```text
Lauf add-fix: passed nach 1 Runde
  Runde 1  Umsetzer  geändert: add.py
  Runde 1  Tests     test_add bestanden
  Runde 1  Review    PASS: AC1 per Lesen geprueft: add.py enthaelt jetzt `ret…
  Abschluss          Fast-forward integriert
Fix add()
def add(a, b):
    return a + b
```

Die `Tests`-Zeile ist das Ergebnis von `test_add.py`, das ki-dev vor dem
Review ausführt. Antwortet das Review `fix`, folgt eine weitere Runde
mit dem Befund.
<!-- /readme-script -->

[↑ Inhalt](#inhalt)

## Stand

- **Mit echten Agenten:** Das Minimalbeispiel lief mit Codex (`gpt-6-luna`)
  und Claude Code (`haiku`) in einer Runde bis zum Commit auf `main`
  ([Ergebnis](#5-ergebnis-ansehen),
  [Ereignisprotokoll](docs/beispiele/echtlauf/9-ergebnis.events.jsonl)).
  Eine Korrekturrunde mit echten Agenten ist noch nicht beobachtet.
- **Mit vorgegebenen Antworten:** Der Ablauf läuft durch Korrektur, Review
  und Übernahme nach `main` ([Demo-Test](tests/readme/test_8_demo.sh)).
- **Freigabe:** `PASS` kann trotz roter Tests zur Übernahme führen.
  Das geplante Test-Tor soll dies verhindern
  ([Anforderungstest](tests/test_review_gate_cli.py)).
- **Verbrauch:** `implement` prüft Grenzen vor jedem Aufruf; eine neue
  Sitzung misst es ab ihrer ersten Antwort. Laufende Verbrauchsmessung mit
  erzwungenem Stopp fehlt; bei Codex auch die Kontextmessung
  ([Verbrauchsschutz](docs/ausfuehrer.de.md#verbrauchsschutz)).
- **Planung:** `map`, `graph` und `materialize` werden mit `step` von Hand
  weitergetragen. Auch Verkettung und Auftragsauswahl übernimmt der Mensch
  ([Planungsbeispiel](docs/vertiefung.de.md#planung)).

[↑ Inhalt](#inhalt)

## Weiterbauen

**Eigene Abläufe** legen Rollen, Schritte und Übergänge in TOML fest;
fachliche Operationen werden in Python ergänzt. ki-dev lädt ein eigenes
Paketverzeichnis über `KI_DEV_FLOW_PATH`.
[Paket anlegen](docs/ablaufpakete.de.md#paket-außerhalb-des-gerüsts)

**Gemeinsame Mechanik:** Der Runner startet Operationen, sichert Ergebnisse
und setzt Läufe nach einem Halt fort. Executoren verbinden ihn mit Agenten
oder Menschen. [Architektur mit Quellen](docs/vertiefung.de.md#architektur)

**Nächste Arbeiten:** Test-Tor, ein gemeinsamer Runner für Umsetzung und
Planung sowie durchgesetzter Verbrauchsschutz.
[Architekturarbeiten](docs/ausfuehrer-luecken.de.md) · [Zielbild](docs/zielbild.de.md)

Warum die Steuerung in Code liegt und welche Forschung den Entwurf
motiviert: [Entwurfsentscheidung](docs/vertiefung.de.md#entwurfsentscheidung).

[↑ Inhalt](#inhalt)

## Mitmachen

Zwei Einstiegspunkte mit prüfbarem Ergebnis:

- **Test-Tor ergänzen:** Die Übernahme bei roten Tests verhindern;
  als Abnahme dient der [Anforderungstest](tests/test_review_gate_cli.py)
  ohne `xfail`.
- **Rundengrenzen für Planung durchsetzen:** Bei `map`, `graph` und
  `materialize` nach verbrauchter Rundengrenze mit einem weiteren `fix`
  einen Halt für den Menschen auslösen.

<!-- readme-script: readme-scripts/7-entwickeln.sh -->
Im Ordner `ki-dev` aus der [Einrichtung](#1-einrichten):

```bash
make test          # pytest und ruff
make spec-test     # Anforderungstests, rote Ergebnisse sind zulässig
make readme-check  # Docker-Prüfung; aktualisiert README und Vertiefung
```

> ⏳ Ungeprüft: Entwicklerbefehle; make readme-check ist dieser Lauf selbst · [Test](tests/readme/test_7_entwickeln.sh)
<!-- /readme-script -->

**Dokumentation ändern:** Befehle und Erklärungen liegen in
[`readme-scripts/`](readme-scripts), Übersetzungen in
[`readme-scripts/en/`](readme-scripts/en).
`.venv/bin/python scripts/render-readme.py` aktualisiert README und
Vertiefung. `make readme-check` benötigt Docker mit Compose und setzt
Prüfstatus und Ausgaben aus genau diesem Lauf direkt unter den jeweiligen
Befehlsblock. `make readme-live` führt das Beispiel mit echten Agenten aus
(verbraucht Tokens) und setzt Status und Ausgabe von Schritt 5.
[Leitlinie](docs/readme-leitlinie.de.md)

Für eigene Entwicklungsläufe:
[ki-dev getrennt vom bearbeiteten Quellbaum installieren](docs/vertiefung.de.md#betriebsinstallation).

Fragen, Ideen, Zusammenarbeit: ein Issue öffnen oder
[@blaumohn](https://github.com/blaumohn) ansprechen.

[↑ Inhalt](#inhalt)

## Lizenz

[MIT](LICENSE)
