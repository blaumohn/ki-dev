#!/usr/bin/env bash
# Stub für readme-scripts/3-review-gate.sh (Übergang bis ki-dev-ablauf-335n).
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

readme_test_missing "Spezifikationstest, entfällt mit ki-dev-ablauf-335n" \
  "spec test, removed with ki-dev-ablauf-335n"
