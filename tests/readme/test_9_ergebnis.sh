#!/usr/bin/env bash
# Test für readme-scripts/9-ergebnis.sh: das ganze Beispiel mit echten
# Agenten, nach 3-auftrag.sh, 4-rollen.sh, 5-starten.sh und
# 9-entscheiden.sh in derselben Shell. Ruft Modelle auf und verbraucht
# Tokens; deshalb nur mit README_LIVE=1 (make readme-live), sonst ein
# Stub. Erwartet: Halt vor der Entscheidung, danach Lauf passed,
# Abschluss-Commit „Fix is_newer()“ auf main und eine verdeckte
# Abnahme gegen version.py auf main, die kein Agent gesehen hat.
# Schreibt auch das Ergebnis von 9-entscheiden.sh (Verlauf bis zum
# Halt); daneben das Ereignisprotokoll (9-ergebnis.events.jsonl).
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

main() {
  local work halt excerpt
  if [[ "${README_LIVE:-}" != 1 ]]; then
    readme_test_missing \
      "braucht angemeldete Agenten-CLIs (make readme-live)" \
      "needs logged-in agent CLIs (make readme-live)"
  fi
  readme_run 3-auftrag.sh 4-rollen.sh 5-starten.sh 9-entscheiden.sh \
    9-ergebnis.sh
  work="$(set -e; readme_workdir)"
  # Beleg neben dem Ergebnis: Ereignisprotokoll dieses Laufs.
  mkdir -p "$README_RESULTS_DIR"
  cp "$work/.ki-dev/runs/version-fix/events.jsonl" \
    "$README_RESULTS_DIR/9-ergebnis.events.jsonl"
  halt="$README_LOG.halt"
  excerpt="$README_LOG.auszug"
  live_excerpts "$README_LOG" "$(cd "$work/.." && pwd)/versions" \
    "$halt" "$excerpt"
  readme_write_entry 9-entscheiden.sh passed "$halt" "" ""
  readme_result passed "$excerpt"
}

# Der erste Endzustand (5-starten.sh) muss ein Halt für die Entscheidung
# sein, kein technischer Halt. Zwei Verläufe von history: der erste
# (9-entscheiden.sh) endet mit dem Halt, der zweite (9-ergebnis.sh) mit
# dem Abschluss. Erfolg wird an Lauf und Ziel-Repo geprüft, nicht nur an
# der Ausgabe.
live_excerpts() {
  python3 - "$@" <<'PY'
import json
import subprocess
import sys

log, versions, halt_file, result_file = sys.argv[1:]
lines = open(log, encoding="utf-8").read().splitlines()
first = lines.index("{")
state = json.loads("\n".join(lines[first:lines.index("}", first) + 1]))
if not (
    state["status"] == "waiting_decision"
    or (
        state["status"] == "paused_interactive"
        and "checks_failed" in (state["detail"] or "")
    )
):
    sys.exit(
        "kein Halt für die Entscheidung nach 5-starten.sh: "
        f"{state['status']}: {state['detail']}"
    )
starts = [i for i, line in enumerate(lines)
          if line.startswith("Lauf version-fix: ")]
if len(starts) != 2:
    sys.exit(f"zwei Verläufe von history erwartet, gefunden: {len(starts)}")


def history(start):
    block = [lines[start]]
    for line in lines[start + 1:]:
        if not line.startswith(("  Runde ", "  Halt ", "  Abschluss ")):
            break
        block.append(line)
    return block


halt, final = history(starts[0]), history(starts[1])
if halt[0].startswith("Lauf version-fix: passed"):
    sys.exit(f"kein Halt vor der Entscheidung: {halt[0]}")
if not final[0].startswith("Lauf version-fix: passed"):
    sys.exit(f"Lauf nach der Entscheidung nicht bestanden: {final[0]}")
subject = subprocess.check_output(
    ["git", "-C", versions, "log", "-1", "--format=%s", "main"], text=True
).strip()
if subject != "Fix is_newer()":
    sys.exit(f"Abschluss-Commit {subject!r} statt 'Fix is_newer()'")
subprocess.run(["python3", "test_version.py"], cwd=versions, check=True)
# Verdeckte Abnahme: Fälle, die weder Test noch Auftrag nennen.
subprocess.run(
    ["python3", "-c",
     "from version import is_newer as n\n"
     "assert n('1.10.0', '1.9.0') and n('2.0.0', '1.9.9')\n"
     "assert n('1.2.10', '1.2.9') and n('10.0.0', '9.9.9')\n"
     "assert not n('1.9.0', '1.10.0') and not n('1.2.3', '1.2.3')\n"],
    cwd=versions, check=True,
)

def git(*args):
    return subprocess.check_output(
        ["git", "-C", versions, *args], text=True
    ).rstrip().splitlines()


# Wie 9-ergebnis.sh: Commit mit geänderten Dateien, dann version.py.
# Höchstens 15 Zeilen (lib.sh); was nicht passt, endet sichtbar in „…“.
result = [
    *final,
    *git("log", "-1", "--stat", "--format=%s", "main"),
    *git("show", "main:version.py"),
]
if len(result) > 15:
    result = result[:14] + ["…"]
# Agentenantworten können den Ort des Wegwerf-Repos nennen.
root = versions.rsplit("/", 1)[0] + "/"


def write(path, block):
    text = "\n".join(line.replace(root, "") for line in block)
    open(path, "w", encoding="utf-8").write(text + "\n")


write(halt_file, halt)
write(result_file, result)
PY
}

main "$@"
