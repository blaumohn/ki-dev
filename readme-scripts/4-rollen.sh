# Weiter in `calc-work`:
#
# ```bash
mkdir -p .ki-dev/profiles       # ki-dev sucht Profile im Startordner
cat >.ki-dev/profiles/default.toml <<'EOF'
workdir = "."                   # Arbeits-Worktree, hier startet ki-dev
access_profile = "write"

[worker]                        # setzt um
executor = "codex"              # Executor aus dem Gerüst
session_id = "019a…"            # eigene Codex-Sitzung eintragen
model = "gpt-5.6-terra"
effort = "high"

[review]                        # prüft, in eigener Sitzung
executor = "claude"
session_id = "b3f1…"            # eigene Claude-Code-Sitzung eintragen
model = "sonnet"
effort = "high"

[[tests]]                       # läuft je Runde, Ergebnis ans Review
name = "test_add"
argv = ["python3", "test_add.py"]

[limits]
changes_rounds = 3              # danach fragt ki-dev den Menschen

[finalization]                  # wohin ein akzeptiertes Ergebnis geht
target_workdir = "../calc"      # Repo aus Schritt 2
target_ref = "refs/heads/main"
commit_message = "Fix add()"
data_mode = "file_proposal"
EOF
# ```
