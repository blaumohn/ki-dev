#!/usr/bin/env bash
# Test für readme-scripts/6-map-step.sh, gestartet im ki-dev-Klon nach
# 1-setup.sh, ohne Agenten: flow show gibt Mermaid aus, step die Übergabe
# an den Kartierungsagenten und nach dem Urteil fix die an die Korrektur.
# Auszug: diese letzte Übergabe.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

main() {
  local excerpt
  readme_run 6-map-step.sh
  grep -q '^stateDiagram-v2$' "$README_LOG"
  grep -q '^Rolle: Kartierungsagent\.$' "$README_LOG"
  grep -q '^Review-Befund (fix, CHANGES, AC1): Section 2 is not mapped$' \
    "$README_LOG"
  excerpt="$README_LOG.auszug"
  last_handoff "$README_LOG" >"$excerpt"
  readme_result passed "$excerpt"
}

# Ab der letzten Zeile "Empfänger:" bis zum Ende; ohne die Zeile mit der
# vergebenen Bead-ID und ohne die Ablaufzeile auf stderr (lokaler Pfad).
last_handoff() {
  awk '/^Empfänger: / { n = 0 }
       !/^(Bead|Ablauf): / { lines[n++] = $0 }
       END { for (i = 0; i < n; i++) print lines[i] }' "$1"
}

main "$@"
