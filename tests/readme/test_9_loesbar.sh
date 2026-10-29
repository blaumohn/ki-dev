#!/usr/bin/env bash
# Test für readme-scripts/9-loesbar.sh, nach 3-auftrag.sh und
# 4-rollen.sh in derselben Shell (ohne die Schritte 4 bis 6: deren Halt
# braucht echte Agenten): Die Dateien aus ImpossibleBench liegen
# unverändert auf main, der Arbeits-Worktree steht auf main, das Profil
# nennt beide Tests, und der Lauf kommt bis zum ersten Agentenaufruf.
# Dort stehen Platzhalter statt codex und claude
# (readme_without_agents). Den echten Lauf prüft test_9_ergebnis.sh mit
# README_LIVE=1 im Zusammenhang aller Schritte.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

main() {
  local work
  readme_without_agents
  readme_run 3-auftrag.sh 4-rollen.sh 9-loesbar.sh
  work="$(set -e; readme_workdir)"
  prepared_for_second_task "$work" "$README_REPO_DIR" "$README_LOG"
  readme_test_missing \
    "der erste Agentenaufruf braucht angemeldete Agenten-CLIs; bis dahin ausgeführt" \
    "the first agent call needs logged-in agent CLIs; run up to there"
}

prepared_for_second_task() {
  python3 - "$@" <<'PY'
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

work, repo, log = map(Path, sys.argv[1:])
source = repo / "docs/beispiele/impossiblebench"
app = work.parent / "app"


def git(*args):
    return subprocess.check_output(
        ["git", "-C", str(app), *args], text=True
    ).strip()


for name in ("palindrome.py", "test_palindrome.py"):
    if git("show", f"main:{name}") + "\n" != (source / name).read_text():
        sys.exit(f"{name} auf main weicht von {source / name} ab")
head = subprocess.check_output(
    ["git", "-C", str(work), "rev-parse", "HEAD"], text=True
).strip()
if head != git("rev-parse", "main"):
    sys.exit("Arbeits-Worktree steht nicht auf main")
with open(work / ".ki-dev/profiles/default.toml", "rb") as file:
    tests = [test["name"] for test in tomllib.load(file)["tests"]]
if tests != ["test_version", "test_palindrome"]:
    sys.exit(f"Profil nennt die Tests {tests!r}")
text = log.read_text(encoding="utf-8")
start = re.search(r"^\{$", text, re.MULTILINE)
if start is None:
    sys.exit("Endzustand des Starts fehlt in der Ausgabe")
result, _ = json.JSONDecoder().raw_decode(text, start.start())
state = (result.get("run_id"), result.get("status"), result.get("phase"))
stub = "codex: in dieser Prüfung nicht verfügbar" in str(result.get("detail"))
if state != ("palindrome", "paused_interactive", "worker_step") or not stub:
    sys.exit(f"Start endet mit {result!r}, nicht am ersten Agentenaufruf")
PY
}

main "$@"
