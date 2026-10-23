#!/usr/bin/env bash
# Einrichtung im leeren Verzeichnis: Klon, venv und beide CLIs.
# Die optionale Demo hat ihren eigenen Test: test_8_demo.sh.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

readme_run 1-setup.sh
"$PWD/ki-dev/.venv/bin/ki-dev" --help >/dev/null
"$PWD/ki-dev/.venv/bin/bd" --version >/dev/null
readme_result passed
