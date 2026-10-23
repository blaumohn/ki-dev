#!/usr/bin/env bash
# Test für readme-scripts/9-ergebnis.sh: das ganze Beispiel mit echten
# Agenten, nach 3-auftrag.sh, 4-rollen.sh und 5-starten.sh in derselben
# Shell. Ruft Modelle auf und verbraucht Tokens; deshalb nur mit
# README_LIVE=1 (make readme-live), sonst ein Stub. Erwartet: Lauf
# passed, Abschluss-Commit „Fix add()“ auf main, test_add.py grün.
# Auszug: Ausgabe von history, Commit-Betreff und add.py auf main;
# daneben das Ereignisprotokoll des Laufs (9-ergebnis.events.jsonl).
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

main() {
  local base excerpt
  if [[ "${README_LIVE:-}" != 1 ]]; then
    readme_test_missing \
      "braucht angemeldete Agenten-CLIs (make readme-live)" \
      "needs logged-in agent CLIs (make readme-live)"
  fi
  base="$(mktemp -d)"
  export TMPDIR="$base"
  readme_run 3-auftrag.sh 4-rollen.sh 5-starten.sh 9-ergebnis.sh
  # Beleg neben dem Ergebnis: Ereignisprotokoll dieses Laufs.
  mkdir -p "$README_RESULTS_DIR"
  cp "$base"/*/calc-work/.ki-dev/runs/add-fix/events.jsonl \
    "$README_RESULTS_DIR/9-ergebnis.events.jsonl"
  excerpt="$README_LOG.auszug"
  live_excerpt "$README_LOG" "$base"/*/calc >"$excerpt"
  readme_result passed "$excerpt"
}

# Erfolg an Lauf und Ziel-Repo prüfen, nicht nur an der Ausgabe; der
# Auszug ist die Ausgabe ab „Lauf add-fix:“ ohne die Ablaufzeile.
live_excerpt() {
  python3 - "$1" "$2" <<'PY'
import subprocess
import sys

log, calc = sys.argv[1:]
text = open(log, encoding="utf-8").read()
start = text.find("Lauf add-fix: ")
if start < 0:
    sys.exit("Verlauf von history fehlt in der Ausgabe")
lines = [
    line for line in text[start:].rstrip().splitlines()
    if not line.startswith("Ablauf: ")
]
if not lines[0].startswith("Lauf add-fix: passed"):
    sys.exit(f"Lauf nicht bestanden: {lines[0]}")
subject = subprocess.check_output(
    ["git", "-C", calc, "log", "-1", "--format=%s", "main"], text=True
).strip()
if subject != "Fix add()":
    sys.exit(f"Abschluss-Commit {subject!r} statt 'Fix add()'")
subprocess.run(["python3", "test_add.py"], cwd=calc, check=True)
print("\n".join(lines))
PY
}

main "$@"
