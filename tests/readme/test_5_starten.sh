#!/usr/bin/env bash
# Stub für readme-scripts/5-starten.sh.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

readme_test_missing \
  "braucht echte Agenten; Mock-Fassung in Ausprobieren ohne Agenten" \
  "needs real agents; mock version in Try without agents"
