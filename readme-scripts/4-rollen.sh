# Das Profil besetzt die Rollen: Codex setzt um, Claude Code prüft.
# Beide nutzen das günstigste Modell ihrer CLI mit Effort `low`; ki-dev
# legt für jede Rolle beim ersten Aufruf eine eigene Sitzung an.
# Weiter in `versions-work`:
#
# ```bash
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

[[tests]]                       # je Runde; rot sperrt die Übernahme
name = "test_version"
argv = ["python3", "test_version.py"]

[limits]
changes_rounds = 2              # höchstens zwei Korrekturrunden

[finalization]                  # wohin ein akzeptiertes Ergebnis geht
target_workdir = "../versions"  # Ziel-Repo mit Branch main
target_ref = "refs/heads/main"
commit_message = "Fix is_newer()"
EOF
# ```
#
# - `executor` lässt sich je Rolle austauschen; vorhanden sind `codex`,
#   `claude`, `mock` und `manual` ([Executoren](docs/ausfuehrer.de.md#executoren)).
# - Grenzen je Aufruf (Zeit, Kosten, Kontingent) haben
#   [Standardwerte](docs/ausfuehrer.de.md#verbrauchsschutz).
