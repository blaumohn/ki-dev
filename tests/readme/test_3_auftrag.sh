#!/usr/bin/env bash
# Test für readme-scripts/3-auftrag.sh, gestartet im ki-dev-Klon nach
# 1-setup.sh (ki-dev und bd im PATH): die letzte Ausgabezeile ist die ID
# des neuen Auftrags (vergeben, kein Auszug).
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

readme_run 3-auftrag.sh
[[ "$(tail -n 1 "$README_LOG")" =~ ^app-[0-9a-z]+$ ]]
readme_result passed
