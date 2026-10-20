# Helfer für die Tests der README-Skripte (tests/readme/test_*.sh), per
# source geladen; wer lib.sh lädt, läuft strikt (errexit, pipefail).
#
# Zuordnung über den Dateinamen: readme-scripts/1-setup.sh gehört zu
# tests/readme/test_1_setup.sh. Je Skript entsteht
# $README_RESULTS_DIR/<Skript ohne .sh>.json, eine JSON-Liste mit einem
# Eintrag je Parameter (ein .sh-Test schreibt genau einen, parameter {}):
#
#   [{"skript": "1-setup.sh", "parameter": {}, "ergebnis": "passed",
#     "datum": "2026-10-20T08:00:00Z", "auszug": ["{", "…"]}]
#
# ergebnis: passed | failed | skipped | stub. grund_de und grund_en nur
# bei stub; auszug nur mit Auszugsdatei, nie bei failed: höchstens 15
# Zeilen, die für Besucher bedeutsam und von Lauf zu Lauf gleich sind
# (keine temporären Pfade, Hashes, vergebenen IDs oder Zeiten). Vertrag:
# RESULT_SCHEMA in scripts/readme_results.py; daraus setzt
# render-readme.py --write Statuszeile und Ausgabeblock der README.
set -Eeuo pipefail
shopt -s inherit_errexit
trap 'echo "[readme-check] Fehler in ${0##*/} Zeile $LINENO: $BASH_COMMAND" >&2' ERR

README_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
README_SCRIPTS_DIR="${README_SCRIPTS_DIR:-$README_REPO_DIR/readme-scripts}"
README_RESULTS_DIR="${README_RESULTS_DIR:-/tmp/readme-ergebnisse}"
README_LOG_DIR="${README_LOG_DIR:-${TMPDIR:-/tmp}/readme-logs}"

# Führt readme-scripts/<skript> … wie ein Besucher im aktuellen
# Verzeichnis aus, mehrere nacheinander in einer Shell wie im selben
# Terminal (Variablen und Verzeichnis gehen weiter). Die Ausgabe steht
# zusätzlich in $README_LOG, benannt nach dem letzten Skript.
readme_run() {
  local script session
  mkdir -p "$README_LOG_DIR"
  README_LOG="$(readme_log_file "${!#}")"
  session="$README_LOG.sh"
  for script in "$@"; do
    cat "$README_SCRIPTS_DIR/$script"
  done >"$session"
  bash -eu -o pipefail "$session" 2>&1 | tee "$README_LOG"
}

# Ergebnis des laufenden Tests; failed endet mit Exit 1.
readme_result() {
  local result="$1" excerpt="${2:-}"
  if [[ "$result" == failed && -n "$excerpt" ]]; then
    echo "[readme-check] readme_result failed: kein Auszug erlaubt" >&2
    return 2
  fi
  readme_write_entry "$(readme_script_for_test "$0")" "$result" \
    "$excerpt" "" ""
  if [[ "$result" == failed ]]; then
    return 1
  fi
}

# Vorläufig fehlender Test oder ungeprüfter Rest nach den Prüfungen
# davor: Begründung als Halbsatz DE/EN, erscheint in der Statuszeile der
# README. Beendet den Test mit Exit 0.
readme_test_missing() {
  local reason_de="$1" reason_en="$2" script
  script="$(readme_script_for_test "$0")"
  readme_write_entry "$script" stub "" "$reason_de" "$reason_en"
  echo "[readme-check] $script: ungeprüft (Stub): $reason_de" >&2
  exit 0
}

# Startet eine Testdatei. Endet sie ohne Ergebnis, steht failed ohne
# Auszug im Ergebnis (Logzeilen enthalten temporäre Pfade); die Diagnose
# geht nur auf stderr. Gibt den Exitcode des Tests weiter.
run_readme_test() {
  local test="$1" script code=0
  script="$(readme_script_for_test "$test")"
  echo "[readme-check] $script: ${test##*/}" >&2
  bash "$test" || code=$?
  if [[ ! -f "$(readme_result_file "$script")" ]]; then
    if (( code == 0 )); then
      echo "[readme-check] $test: endete ohne Ergebnis" >&2
      code=1
    fi
    readme_write_entry "$script" failed "" "" ""
  fi
  if (( code != 0 )); then
    readme_report_failure "$test" "$script" "$code"
  fi
  return "$code"
}

readme_report_failure() {
  local test="$1" script="$2" code="$3" log
  log="$(readme_log_file "$script")"
  echo "[readme-check] $test fehlgeschlagen (Exit $code); Log: $log" >&2
  if [[ -f "$log" ]]; then
    tail -n 15 "$log" >&2
  fi
}

# test_1_setup.sh (oder .py) → 1-setup.sh
readme_script_for_test() {
  local name="${1##*/}"
  name="${name#test_}"
  name="${name%.*}"
  printf '%s.sh\n' "${name//_/-}"
}

readme_result_file() {
  printf '%s/%s.json\n' "$README_RESULTS_DIR" "${1%.sh}"
}

readme_log_file() {
  printf '%s/%s.log\n' "$README_LOG_DIR" "${1%.sh}"
}

# Schreibt die Ergebnisdatei eines Skripts (ein Eintrag, parameter {}).
readme_write_entry() {
  local script="$1" result="$2" excerpt="$3" reason_de="$4" reason_en="$5"
  mkdir -p "$README_RESULTS_DIR"
  python3 - "$(readme_result_file "$script")" "$script" "$result" \
    "$excerpt" "$reason_de" "$reason_en" <<'PY'
import datetime
import json
import os
import sys

path, script, result, excerpt, reason_de, reason_en = sys.argv[1:]
MAX_LINES = 15
if result not in ("passed", "failed", "skipped", "stub"):
    sys.exit(f"[readme-check] {script}: unbekanntes Ergebnis {result!r}")
entry = {"skript": script, "parameter": {}, "ergebnis": result}
if result == "stub":
    if not (reason_de.strip() and reason_en.strip()):
        sys.exit(f"[readme-check] {script}: Stub ohne Halbsatz DE/EN")
    entry |= {"grund_de": reason_de, "grund_en": reason_en}
now = datetime.datetime.now(datetime.UTC)
entry["datum"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
if excerpt:
    with open(excerpt, encoding="utf-8") as file:
        lines = file.read().splitlines()
    if len(lines) > MAX_LINES:
        sys.exit(
            f"[readme-check] {script}: Auszug mit {len(lines)} Zeilen, "
            f"höchstens {MAX_LINES}"
        )
    local_paths = {"/tmp/", os.environ.get("TMPDIR"), os.environ.get("HOME")}
    for number, line in enumerate(lines, 1):
        if any(p and p in line for p in local_paths):
            sys.exit(
                f"[readme-check] {script}: Auszug Zeile {number} "
                "enthält einen lokalen Pfad"
            )
    entry["auszug"] = lines
with open(path, "w", encoding="utf-8") as file:
    json.dump([entry], file, ensure_ascii=False, indent=2)
    file.write("\n")
PY
}
