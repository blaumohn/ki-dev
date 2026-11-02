#!/usr/bin/env bash
# Offline-Vorführung von `ki-dev -f implement`: Umsetzung mit Mock-Adaptern.
#
# Legt in einem Wegwerfverzeichnis ein Git-Repo (Ziel-Worktree `main`,
# Arbeits-Worktree `arbeit`) mit Beads-Projekt und Profil an und fährt
# einen Lauf für einen Bead:
# Bau → Review CHANGES → Bau → Review PASS → geprüfte Integration.
# Kein Anbieterzugang nötig; braucht git, bd und das Projekt-venv.
#
#   scripts/demo-mock-lauf.sh [VERZEICHNIS]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# CLI und Ablauf gehören zum Checkout, auch bei älterem installiertem Paket.
export PYTHONPATH="$ROOT/src"
FLOW="$ROOT/src/ki_dev/flow/implement.toml"
KI_DEV="${KI_DEV:-$ROOT/.venv/bin/ki-dev}"
DEMO="${1:-$(mktemp -d)/ki-dev-demo}"
export GIT_AUTHOR_NAME=demo GIT_AUTHOR_EMAIL=demo@example.invalid
export GIT_COMMITTER_NAME=demo GIT_COMMITTER_EMAIL=demo@example.invalid

mkdir -p "$DEMO"
git init -q -b main "$DEMO/ziel"
printf '.beads.gate.lock\n' >"$DEMO/ziel/.gitignore"
git -C "$DEMO/ziel" add .gitignore
git -C "$DEMO/ziel" commit -q -m start
git -C "$DEMO/ziel" worktree add -q -b arbeit "$DEMO/arbeit"
echo "[demo] Beads initialisieren: $DEMO/arbeit" >&2
(cd "$DEMO/arbeit" && bd init --quiet --prefix demo --skip-agents --skip-hooks \
  --stealth --non-interactive)

echo "[demo] Bead erstellen" >&2
BEAD="$(cd "$DEMO/arbeit" && bd create "MOCK.md je Runde ergänzen" \
  --description "MOCK.md um eine Zeile je Runde ergänzen" \
  --design "Mock-Adapter schreiben die Zeile" \
  --acceptance "1. MOCK.md existiert
2. [error] entfällt: der Mock schreibt nur eine Zeile" --silent)"

cat >"$DEMO/profil.toml" <<EOF
workdir = "$DEMO/arbeit"
access_profile = "write"
tests = []

[finalization]
target_workdir = "$DEMO/ziel"
target_ref = "refs/heads/main"
commit_message = "Geprüfter Abschluss (Demo)"
data_mode = "file_proposal"

[worker]
executor = "mock"

[review]
executor = "mock"
answers = ["fix", "PASS"]
EOF

echo "[demo] Mock-Lauf starten: $BEAD" >&2
if (cd "$DEMO/arbeit" && "$KI_DEV" -f "$FLOW" "$BEAD" \
  --profile "$DEMO/profil.toml" --run-id demo --runs-dir "$DEMO/runs" \
  >"$DEMO/result.json"); then
  :
else
  demo_status=$?
  cat "$DEMO/result.json" >&2
  exit "$demo_status"
fi
"$ROOT/.venv/bin/python" - "$DEMO/result.json" <<'PY'
import json
import sys

result = json.loads(open(sys.argv[1], encoding="utf-8").read())
if result["status"] != "passed":
    sys.exit(str(result.get("detail", "Demo nicht abgeschlossen")))
PY
echo "Demo-Verlauf (Platzhalter-Agenten mit vorgegebenen Antworten):"
(cd "$DEMO/arbeit" && "$KI_DEV" -f "$FLOW" history demo \
  --runs-dir "$DEMO/runs")
echo "Datei auf main: ziel/MOCK.md"
sed 's/^/  /' "$DEMO/ziel/MOCK.md"
echo "Laufverzeichnis: $DEMO/runs/demo"
