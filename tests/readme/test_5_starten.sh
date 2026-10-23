#!/usr/bin/env bash
# Test für readme-scripts/5-starten.sh, nach 3-auftrag.sh und
# 4-rollen.sh in derselben Shell wie bei einem Besucher: Arbeits-Worktree
# und Profil passen zum Start, der Lauf kommt bis zum ersten
# Agentenaufruf. Dort stehen Platzhalter statt codex und claude
# (readme_without_agents); der Lauf hält mit ihrem Fehler an. Den
# echten Lauf prüft test_9_ergebnis.sh mit README_LIVE=1.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

main() {
  readme_without_agents
  readme_run 3-auftrag.sh 4-rollen.sh 5-starten.sh
  stops_at_first_agent_call "$README_LOG"
  readme_test_missing \
    "der erste Agentenaufruf braucht angemeldete Agenten-CLIs; bis dahin ausgeführt" \
    "the first agent call needs logged-in agent CLIs; run up to there"
}

# `ki-dev -f implement` gibt den Endzustand als JSON-Objekt ab einer
# Zeile "{" aus; erwartet: Halt im Worker-Schritt am Fehler des
# Platzhalters, also nach dem Start des ersten Agentenaufrufs.
stops_at_first_agent_call() {
  python3 - "$1" <<'PY'
import json
import re
import sys

text = open(sys.argv[1], encoding="utf-8").read()
start = re.search(r"^\{$", text, re.MULTILINE)
if start is None:
    sys.exit("Endzustand des Starts fehlt in der Ausgabe")
result, _ = json.JSONDecoder().raw_decode(text, start.start())
state = (result.get("run_id"), result.get("status"), result.get("phase"))
stub = "codex: in dieser Prüfung nicht verfügbar" in str(result.get("detail"))
if state != ("add-fix", "paused_interactive", "worker_step") or not stub:
    sys.exit(f"Start endet mit {result!r}, nicht am ersten Agentenaufruf")
PY
}

main "$@"
