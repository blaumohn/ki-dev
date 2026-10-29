# Jeder Lauf liest das Profil beim Start, ohne `--profile` das Profil
# `default`; ki-dev legt je Rolle beim ersten Aufruf eine eigene Sitzung
# an. Weiter in `app-work`:
#
# ```bash
mkdir -p .ki-dev/profiles       # ki-dev sucht Profile im Startordner
cat >.ki-dev/profiles/default.toml <<'EOF'
workdir = "."                   # Arbeits-Worktree, hier startet ki-dev
access_profile = "write"        # der Umsetzer darf hier schreiben

[worker]                        # setzt um; in history: Umsetzer
executor = "codex"
model = "gpt-6-luna"            # günstigstes Modell der CLI
effort = "low"

[review]                        # prüft, nur lesend
executor = "claude"
model = "haiku"                 # günstigstes Modell der CLI
effort = "low"

[[tests]]                       # Tests des Repos; der Ablauf ruft sie
name = "test_version"
argv = ["python3", "test_version.py"]

[limits]
changes_rounds = 2              # höchstens zwei Korrekturrunden

[safety_limits]
max_agent_calls = 10            # Agentenaufrufe im ganzen Lauf

[finalization]                  # wohin ein akzeptiertes Ergebnis geht
target_workdir = "../app"       # Ziel-Repo mit Branch main
target_ref = "refs/heads/main"
commit_message = "Tests green, review PASS"  # für jeden Auftrag
EOF
# ```
#
# - `executor` lässt sich je Rolle austauschen; vorhanden sind `codex`,
#   `claude`, `mock` und `manual` ([Executoren](docs/ausfuehrer.de.md#executoren)).
# - `max_agent_calls` begrenzt die Agentenaufrufe des ganzen Laufs,
#   Wiederholungen nach leeren oder ungültigen Antworten eingeschlossen
#   (Standard 6). Grenzen je Aufruf (Zeit, Kosten, Kontingent) haben
#   [Standardwerte](docs/ausfuehrer.de.md#verbrauchsschutz).
