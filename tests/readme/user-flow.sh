#!/usr/bin/env bash
# README-Einrichtung wie ein Besucher: aus einem leeren Verzeichnis klonen,
# dann je README-Skript seinen Test (tests/readme/test_*.sh, Helfer in
# lib.sh), README-Abschnitte, Tests, Lint. Reihenfolge und Arbeitsverzeichnis
# legt dieser Ablauf fest; jeder Test schreibt sein Ergebnis nach
# $README_RESULTS_DIR. Scheitert ein Test, bleiben die folgenden Skripte
# ohne Ergebnis („nicht ausgeführt“).
#
# Läuft im Wegwerf-Container (make readme-check, compose.readme-check.yaml).
# Geprüft wird der lokale Arbeitsstand: versionierte Änderungen und
# unversionierte, nicht ignorierte Dateien, committet nur im temporären Klon.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

SOURCE_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_BASE="${READMECHECK_WORK_BASE:-$(mktemp -d)}"
GIT_DAEMON_PORT="${GIT_DAEMON_PORT:-9418}"
git_daemon_pid=""
staging_dir=""

main() {
  local user_dir
  trap 'stop_git_server' EXIT
  mkdir -p "$WORK_BASE" "$HOME"

  step "Arbeitsstand in temporären Klon übernehmen"
  prepare_staging_repo "$SOURCE_REPO_DIR"
  step "Git-Server starten"
  start_git_server "$staging_dir"

  export README_SCRIPTS_DIR="$staging_dir/readme-scripts"
  export README_LOG_DIR="$WORK_BASE/logs"

  step "README-Einrichtung aus leerem Verzeichnis"
  user_dir="$(mktemp -d "$WORK_BASE/visitor-XXXXXX")"
  cd "$user_dir"
  run_readme_test "$staging_dir/tests/readme/test_1_setup.sh"

  # Ab hier wie ein Besucher nach 1-setup.sh: im ki-dev-Klon.
  cd "$user_dir/ki-dev"
  step "README-Abschnitte gegen readme-scripts prüfen"
  .venv/bin/python scripts/render-readme.py --check
  step "Übrige README-Skripte im Klon des Besuchers"
  run_readme_test "$staging_dir/tests/readme/test_2_runtime.sh"
  run_readme_test "$staging_dir/tests/readme/test_3_review_gate.sh"
  step "Tests und Lint im Klon des Besuchers"
  # bd liegt im venv; Tests finden es wie bei aktiviertem venv im PATH.
  PATH="$PWD/.venv/bin:$PATH" .venv/bin/pytest -q -m "not docker"
  .venv/bin/ruff check .
  step "README-Einrichtung bestanden"
}

step() {
  echo "[readme-check] $*" >&2
}

# Klon des Quell-Repos mit dessen Arbeitsstand, committet nur im Klon.
# Setzt staging_dir; jeder Fehler bricht ab (kein &&, keine Substitution).
prepare_staging_repo() {
  local source="$1" base
  base="$(mktemp -d "$WORK_BASE/staging-XXXXXX")"
  staging_dir="$base/ki-dev"
  git clone --quiet --no-local "$source" "$staging_dir"
  apply_tracked_changes "$source" "$staging_dir" "$base/working.patch"
  copy_untracked_files "$source" "$staging_dir" "$base/untracked.list"
  commit_working_state "$staging_dir"
}

apply_tracked_changes() {
  local source="$1" target="$2" patch="$3"
  git -C "$source" diff --binary HEAD >"$patch"
  if [[ -s "$patch" ]]; then
    git -C "$target" apply --whitespace=nowarn "$patch"
  fi
}

copy_untracked_files() {
  local source="$1" target="$2" list="$3" file
  git -C "$source" ls-files -z --others --exclude-standard >"$list"
  while IFS= read -r -d '' file; do
    mkdir -p "$target/$(dirname "$file")"
    cp "$source/$file" "$target/$file"
  done <"$list"
}

commit_working_state() {
  local target="$1"
  git -C "$target" add -A
  if git -C "$target" diff --cached --quiet; then return 0; fi
  git -C "$target" -c user.name="readme-check" \
    -c user.email="readme-check@example.invalid" \
    commit --quiet --no-verify -m "tmp: lokaler Arbeitsstand"
}

start_git_server() {
  local repo_dir="$1"
  git daemon --reuseaddr --listen=127.0.0.1 --port="$GIT_DAEMON_PORT" \
    --base-path="$(dirname "$repo_dir")" --export-all "$repo_dir" &
  git_daemon_pid="$!"
  REPLACE_WITH_REPOSITORY_URL="git://127.0.0.1:${GIT_DAEMON_PORT}/ki-dev"
  export REPLACE_WITH_REPOSITORY_URL
  for _ in $(seq 1 10); do
    if git ls-remote "$REPLACE_WITH_REPOSITORY_URL" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "[readme-check] git daemon antwortet nicht rechtzeitig" >&2
  return 1
}

stop_git_server() {
  if [[ -n "${git_daemon_pid:-}" ]]; then
    kill "$git_daemon_pid" 2>/dev/null || true
    wait "$git_daemon_pid" 2>/dev/null || true
  fi
}

# Nur direkt aufgerufen ausführen; Tests laden die Funktionen per source.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
