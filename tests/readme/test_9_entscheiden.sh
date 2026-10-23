#!/usr/bin/env bash
# Test für readme-scripts/9-entscheiden.sh: Die Entscheidung folgt auf
# den Halt eines echten Laufs. Ohne angemeldete Agenten-CLIs gibt es
# diesen Halt nicht; den Schritt führt test_9_ergebnis.sh mit
# README_LIVE=1 (make readme-live) im Zusammenhang aus und schreibt
# dabei auch das Ergebnis dieses Skripts.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

readme_test_missing \
  "braucht angemeldete Agenten-CLIs (make readme-live)" \
  "needs logged-in agent CLIs (make readme-live)"
