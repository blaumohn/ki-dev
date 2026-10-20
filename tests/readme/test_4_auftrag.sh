#!/usr/bin/env bash
# Test für readme-scripts/4-auftrag.sh, gestartet im ki-dev-Klon nach
# 1-setup.sh: der Block richtet PATH und Beads-Projekt selbst ein; die
# letzte Ausgabezeile ist die ID des neuen Auftrags (vergeben, kein Auszug).
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

readme_run 4-auftrag.sh
[[ "$(tail -n 1 "$README_LOG")" =~ ^calc-[0-9a-z]+$ ]]
readme_result passed
