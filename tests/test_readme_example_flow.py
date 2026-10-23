"""README-Beispiel, Schritte 2 bis 6, mit vorgegebenen Antworten statt
Agenten (ki-dev-ablauf-7v99).

Dieselben ``readme-scripts`` wie in der README; ``--adapter inbox``
ersetzt Codex und Claude, die Antworten legt der Test als Datei ab.
Belegt die Mechanik des Wegs Halt → Bead geändert, ``resume`` →
Korrekturrunde → ``main`` für beide Halte (Review ``decision`` und
Test-Tor nach ``PASS`` bei roten Tests), nicht die Leistung eines
Agenten; die zeigt ``make readme-live``. Braucht ``bd``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "readme-scripts"

# Ein Besucher im selben Terminal; Rollen über inbox. answer legt die
# Antwort auf die eine offene Eingabe ab, resume setzt fort.
DRIVER = r"""
set -euo pipefail
RUN=version-fix
answer() {
  local input open=()
  for input in ".ki-dev/runs/$RUN/inbox/"*.input.md; do
    [[ -e "${input%.input.md}.answer.md" ]] || open+=("$input")
  done
  if (( ${#open[@]} != 1 )); then
    echo "offene Eingaben: ${open[*]}" >&2
    exit 1
  fi
  printf '%s\n' "$1" >"${open[0]%.input.md}.answer.md"
}
review() {  # $1 Runde, $2 Ereignis, $3 Befund, $4 Kriterium
  answer "{\"run_id\":\"$RUN\",\"round_id\":$1,\"event\":\"$2\",
\"detail\":\"$3\",\"requirement_ref\":$4}"
}
step() { ki-dev -f implement resume "$RUN" --adapter inbox >/dev/null; }
inbox() {
  sed "s/--run-id $RUN/& --adapter inbox/;
       s/implement resume $RUN /&--adapter inbox /" "$1"
}
source "$SCRIPTS/3-auftrag.sh"
source "$SCRIPTS/4-rollen.sh"
# Bash 3.2 kann source nicht aus einer Prozesssubstitution lesen.
inbox "$SCRIPTS/5-starten.sh" >"$TMPDIR/5-starten-inbox.sh"
source "$TMPDIR/5-starten-inbox.sh" >/dev/null
printf 'def is_newer(a, b):\n    return %s > %s\n' \
  'tuple(map(int, a.split(".")))' 'tuple(map(int, b.split(".")))' \
  >version.py
answer '{}'; step
review 1 "$REVIEW" "Test widerspricht AC1" null; step || true
echo "=== Schritt 5"
inbox "$SCRIPTS/9-entscheiden.sh" >"$TMPDIR/9-entscheiden-inbox.sh"
source "$TMPDIR/9-entscheiden-inbox.sh"
review 1 fix "Test laut Entscheidung anpassen" '"AC2"'; step
sed -i 's/^assert not is_newer/assert is_newer/' test_version.py
answer '{}'; step
review 2 PASS "AC1 erfüllt" null; step
echo "=== Schritt 6"
source "$SCRIPTS/9-ergebnis.sh"
"""


@pytest.mark.parametrize(
    ("review", "halt"),
    [
        (
            "decision",
            "Halt wartet auf Entscheidung (Bead ändern, resume)",
        ),
        ("PASS", "Halt checks_failed: Review PASS bei roter Prüfung:"),
    ],
)
def test_readme_example_halts_then_merges_after_answer(
    tmp_path, review, halt
):
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "KI_DEV_FLOW_PATH" and not key.startswith("GIT_")
    }
    env |= {
        "PATH": f"{ROOT / '.venv' / 'bin'}:{env['PATH']}",
        "TMPDIR": str(tmp_path),
        "SCRIPTS": str(SCRIPTS),
        "REVIEW": review,
    }
    completed = subprocess.run(
        ["bash", "-c", DRIVER],
        env=env, text=True, capture_output=True, check=False,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr[-3000:]
    halted, _, finished = completed.stdout.partition("=== Schritt 6")
    halted = halted.partition("=== Schritt 5")[2]

    assert " ".join(halted.split()).count(halt) == 1, halted
    final = [line.split() for line in finished.splitlines() if line]
    assert final[0][:3] == ["Lauf", "version-fix:", "passed"]
    assert [line[:4] for line in final[1:10]] == [
        ["Runde", "1", "Umsetzer", "geändert:"],
        ["Runde", "1", "Tests", "test_version"],
        ["Runde", "1", "Review", f"{review}:"],
        ["Runde", "1", "Mensch", "AC2"],
        ["Runde", "1", "Review", "fix"],
        ["Runde", "2", "Umsetzer", "geändert:"],
        ["Runde", "2", "Tests", "test_version"],
        ["Runde", "2", "Review", "PASS:"],
        ["Abschluss", "Fast-forward", "integriert"],
    ]
    assert ["Fix", "is_newer()"] in final
