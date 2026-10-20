#!/usr/bin/env bash
# Test für readme-scripts/4-rollen.sh, nach 3-auftrag.sh in derselben
# Shell: das HERE-Doc legt im Arbeits-Worktree ein gültiges Profil mit
# den Rollen worker und review ab. Ob ki-dev damit startet, prüft
# test_5_starten.sh. TMPDIR macht den Ort von mktemp -d auffindbar.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

main() {
  local base
  base="$(mktemp -d)"
  export TMPDIR="$base"
  readme_run 3-auftrag.sh 4-rollen.sh
  profile_has_roles "$base"/*/calc-work/.ki-dev/profiles/default.toml
  readme_result passed
}

profile_has_roles() {
  python3 - "$@" <<'PY'
import sys
import tomllib

if len(sys.argv) != 2:
    sys.exit(f"genau ein Profil erwartet: {sys.argv[1:]}")
with open(sys.argv[1], "rb") as file:
    profile = tomllib.load(file)
roles = {name: profile[name]["executor"] for name in ("worker", "review")}
if roles != {"worker": "codex", "review": "claude"}:
    sys.exit(f"Profil mit Rollen {roles!r}")
PY
}

main "$@"
