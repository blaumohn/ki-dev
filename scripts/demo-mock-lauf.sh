#!/usr/bin/env bash
# Offline-Vorführung von `ki-dev run`: Bauablauf mit Mock-Adaptern.
#
# Legt in einem Wegwerfverzeichnis ein Git-Repo (Ziel-Worktree `main`,
# Arbeits-Worktree `arbeit`) mit Beads-Projekt an und fährt einen Lauf:
# Bau → Review CHANGES → Bau → Review PASS → geprüfte Integration.
# Kein Anbieterzugang nötig; braucht git, bd und das Projekt-venv.
#
#   scripts/demo-mock-lauf.sh [VERZEICHNIS]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
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
(cd "$DEMO/arbeit" && bd init --prefix demo --skip-agents --skip-hooks \
  --stealth >/dev/null)

cat >"$DEMO/lauf.json" <<EOF
{
  "task": "MOCK.md um eine Zeile je Runde ergänzen",
  "acceptance_criteria": ["MOCK.md existiert"],
  "sources": [],
  "workdir": "$DEMO/arbeit",
  "access_profile": "write",
  "finalization": {
    "target_workdir": "$DEMO/ziel",
    "target_ref": "refs/heads/main",
    "commit_message": "Geprüfter Abschluss (Demo)",
    "data_mode": "file_proposal"
  },
  "worker": {"executor": "mock"},
  "review": {"executor": "mock", "answers": ["fix", "PASS"]},
  "tests": []
}
EOF

"$KI_DEV" run --config "$DEMO/lauf.json" --run-id demo \
  --runs-dir "$DEMO/runs"
echo
git -C "$DEMO/ziel" log --oneline
echo "Laufverzeichnis: $DEMO/runs/demo"
