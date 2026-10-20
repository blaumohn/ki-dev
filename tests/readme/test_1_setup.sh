#!/usr/bin/env bash
# Test für readme-scripts/1-setup.sh, gestartet in einem leeren
# Verzeichnis: Klon, make setup, PATH, make demo; der Demo-Lauf endet
# mit status passed in Runde 2. Auszug: Ergebnis-JSON und Commit-Betreffs.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

main() {
  local excerpt
  readme_run 1-setup.sh
  excerpt="$README_LOG.auszug"
  demo_excerpt "$README_LOG" >"$excerpt"
  readme_result passed "$excerpt"
}

# `ki-dev -f implement` gibt den Endzustand als JSON-Objekt ab einer
# Zeile "{" aus, danach die Commit-Betreffe des Ziel-Repos (ohne Hash)
# bis "Laufverzeichnis:".
demo_excerpt() {
  python3 - "$1" <<'PY'
import json
import re
import sys

text = open(sys.argv[1], encoding="utf-8").read()
start = re.search(r"^\{$", text, re.MULTILINE)
if start is None:
    sys.exit("Demo-Endzustand fehlt in der Ausgabe")
result, end = json.JSONDecoder().raw_decode(text, start.start())
if (result.get("status"), result.get("round_id")) != ("passed", 2):
    sys.exit(f"Demo-Endzustand {result!r} statt status passed, round_id 2")
log = text[end:].split("\nLaufverzeichnis:", 1)[0]
subjects = [line for line in log.splitlines() if line.strip()]
print(text[start.start():end])
print()
print("\n".join(subjects))
PY
}

main "$@"
