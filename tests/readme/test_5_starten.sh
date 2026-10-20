#!/usr/bin/env bash
# Test für readme-scripts/5-starten.sh, nach 3-auftrag.sh und
# 4-rollen.sh in derselben Shell wie bei einem Besucher: Arbeits-Worktree
# und Profil passen zum Start, der Lauf kommt bis zum ersten
# Agentenaufruf. Den
# lehnt der Schutz mit den Platzhalter-Sitzungen ab; was danach kommt,
# braucht echte Agenten und bleibt Stub.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

main() {
  readme_run 3-auftrag.sh 4-rollen.sh 5-starten.sh
  stops_at_first_agent_call "$README_LOG"
  readme_test_missing \
    "der erste Agentenaufruf braucht echte Sitzungen; bis dahin ausgeführt" \
    "the first agent call needs real sessions; run up to there"
}

# `ki-dev -f implement` gibt den Endzustand als JSON-Objekt ab einer
# Zeile "{" aus; erwartet: Halt im Worker-Schritt, weil der Schutz ohne
# Nachweis der Sitzung keinen Aufruf zulässt.
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
guard = "kein Aufruf ohne Nachweis" in str(result.get("detail"))
if state != ("add-fix", "paused_interactive", "worker_step") or not guard:
    sys.exit(f"Start endet mit {result!r}, nicht am ersten Agentenaufruf")
PY
}

main "$@"
