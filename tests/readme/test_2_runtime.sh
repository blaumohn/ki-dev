#!/usr/bin/env bash
# Test für readme-scripts/2-runtime.sh, gestartet im ki-dev-Klon nach
# 1-setup.sh: getrenntes Betriebs-venv, Update nur mit make setup-runtime.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

main() {
  readme_run 2-runtime.sh
  check_runtime_installation
  readme_result passed
}

check_runtime_installation() {
  local runtime="${XDG_DATA_HOME:-$HOME/.local/share}/ki-dev/venv"
  local module=src/ki_dev/runtime_setup_probe.py
  local installed="$runtime/bin/python"
  # Nur im Besucher-Klon: gleichbleibende Paketversion, neuer Quellinhalt.
  printf 'VALUE = "first"\n' > "$module"
  make setup-runtime
  "$installed" -I -c 'from ki_dev.runtime_setup_probe import VALUE; assert VALUE == "first"'
  printf 'VALUE = "second"\n' > "$module"
  "$installed" -I -c 'from ki_dev.runtime_setup_probe import VALUE; assert VALUE == "first"'
  make setup-runtime
  "$installed" -I -c 'from ki_dev.runtime_setup_probe import VALUE; assert VALUE == "second"'
  [[ $(readlink "$HOME/.local/bin/ki-dev") == "$runtime/bin/ki-dev" ]]
  "$HOME/.local/bin/ki-dev" --help >/dev/null
  rm "$module"
}

main "$@"
