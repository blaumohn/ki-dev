#!/usr/bin/env bash
# Test für readme-scripts/8-demo.sh, gestartet im
# ki-dev-Klon nach der Einrichtung: make demo; der Demo-Lauf endet
# mit status passed in Runde 2. Auszug: Ablauf und Ergebnisdatei.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

main() {
  local excerpt
  readme_run 8-demo.sh
  excerpt="$README_LOG.auszug"
  demo_excerpt "$README_LOG" >"$excerpt"
  readme_result passed "$excerpt"
}

# Demo-Ausgabe aus dem Log; den Erfolg zusätzlich an den Artefakten
# prüfen, damit ein fest ausgegebener Erfolgs-Text nicht genügt.
demo_excerpt() {
  python3 - "$1" <<'PY'
import json
import re
import subprocess
import sys
from pathlib import Path

text = open(sys.argv[1], encoding="utf-8").read()
match = re.search(r"^Laufverzeichnis: (.+)$", text, re.MULTILINE)
if match is None:
    sys.exit("Demo-Laufverzeichnis fehlt in der Ausgabe")
run = Path(match[1])
demo = run.parent.parent
result = json.loads((demo / "result.json").read_text())
if (result.get("status"), result.get("round_id")) != ("passed", 2):
    sys.exit(f"Demo-Endzustand {result!r} statt status passed, round_id 2")
events = [json.loads(line) for line in (run / "events.jsonl").read_text().splitlines()]
reviews = [e["event"] for e in events if e["region"] == "ablauf"
           and e["event"] in {"fix", "PASS"}]
if reviews != ["fix", "PASS"]:
    sys.exit(f"Review-Folge {reviews!r} statt fix, PASS")
if (demo / "ziel/MOCK.md").read_text() != "Runde 1\nRunde 2\n":
    sys.exit("Ergebnis beider Runden fehlt auf main")
committed = subprocess.check_output(
    ["git", "-C", str(demo / "ziel"), "show", "main:MOCK.md"], text=True
)
if committed != "Runde 1\nRunde 2\n":
    sys.exit("Ergebnis beider Runden fehlt im Ziel-Commit")
start = text.find(
    "Demo-Verlauf (Platzhalter-Agenten mit vorgegebenen Antworten):\n"
)
if start < 0:
    sys.exit("Erklärender Demo-Verlauf fehlt")
excerpt = [
    line for line in text[start:match.start()].rstrip().splitlines()
    if not line.startswith("Ablauf: ")  # Pfad des Ablaufs, stderr
]
for expected in ("Runde 1  Review    fix", "Runde 2  Review    PASS",
                 "Abschluss"):
    if not any(expected in line for line in excerpt):
        sys.exit(f"Demo-Verlauf ohne: {expected}")
print("\n".join(excerpt))
PY
}

main "$@"
