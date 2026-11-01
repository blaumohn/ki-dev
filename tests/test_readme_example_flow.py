"""README-Beispiel, Schritte 2 bis 7, mit vorgegebenen Antworten statt
Agenten (ki-dev-ablauf-7v99, ki-dev-ablauf-eoqf).

Dieselben ``readme-scripts`` wie in der README; ``--adapter inbox``
ersetzt Codex und Claude, die Antworten legt der Test als Datei ab.
Belegt die Mechanik des Wegs Halt → Bead geändert, ``resume`` →
``main`` für jeden Halt: Frage des Umsetzers (der Weg des
dokumentierten echten Laufs), Review ``decision`` und Test-Tor nach
``PASS`` bei roten Tests, die beiden letzten mit Korrekturrunde. Danach
der lösbare zweite Auftrag (Schritt 7) ohne Halt bis ``main``. Nicht
die Leistung eines Agenten, die zeigt ``make readme-live``. Braucht
``bd``.
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
work() {  # Bericht des Umsetzers nach dem Worker-Vertrag
  answer '{"outcome":"completed","summary":"erledigt"}'
}
review() {  # $1 Runde, $2 Ereignis, $3 Befund, $4 Kriterium
  answer "{\"run_id\":\"$RUN\",\"round_id\":$1,\"event\":\"$2\",
\"detail\":\"$3\",\"requirement_ref\":$4}"
}
step() { ki-dev -f implement resume "$RUN" --adapter inbox >/dev/null; }
inbox() {
  sed -E "s/--run-id [a-z-]+/& --adapter inbox/;
       s/implement resume [a-z-]+ /&--adapter inbox /" "$1"
}
source "$SCRIPTS/3-auftrag.sh"
source "$SCRIPTS/4-rollen.sh"
# Bash 3.2 kann source nicht aus einer Prozesssubstitution lesen.
inbox "$SCRIPTS/5-starten.sh" >"$TMPDIR/5-starten-inbox.sh"
source "$TMPDIR/5-starten-inbox.sh" >/dev/null
for _ in $(seq "$EMPTY"); do work; step; done  # ohne Änderung
fix_version() {
  printf 'def is_newer(a, b):\n    return %s > %s\n' \
    'tuple(map(int, a.split(".")))' 'tuple(map(int, b.split(".")))' \
    >version.py
}
if [[ $REVIEW == worker ]]; then
  answer '{"outcome":"needs_decision",
"summary":"Test widerspricht AC1"}'
  step || true
else
  fix_version
  work; step
  review 1 "$REVIEW" "Test widerspricht AC1" null; step || true
fi
echo "=== Schritt 5"
inbox "$SCRIPTS/9-entscheiden.sh" >"$TMPDIR/9-entscheiden-inbox.sh"
source "$TMPDIR/9-entscheiden-inbox.sh"
if [[ $REVIEW == worker ]]; then
  fix_version
  sed -i 's/^assert not is_newer/assert is_newer/' test_version.py
  work; step
  review 1 PASS "AC1 erfüllt" null; step
else
  review 1 fix "Test laut Entscheidung anpassen" '"AC2"'; step
  sed -i 's/^assert not is_newer/assert is_newer/' test_version.py
  work; step
  review 2 PASS "AC1 erfüllt" null; step
fi
echo "=== Schritt 6"
source "$SCRIPTS/9-ergebnis.sh"
echo "=== Schritt 7"
inbox "$SCRIPTS/9-loesbar.sh" >"$TMPDIR/9-loesbar-inbox.sh"
source "$TMPDIR/9-loesbar-inbox.sh" >/dev/null
RUN=palindrome
cat >palindrome.py <<'EOF'
def shortest_palindrome_with_prefix(s: str) -> str:
    for i in range(len(s)):
        if s[i:] == s[i:][::-1]:
            return s + s[:i][::-1]
EOF
work; step
review 1 PASS "Tests grün" null; step
ki-dev -f implement history palindrome
git -C ../app log -1 --format=%s main
git -C ../app show main:test_palindrome.py >"$TMPDIR/test_palindrome.py"
"""


_DECISION_HALT = "Halt wartet auf Entscheidung (Bead ändern, resume)"
_TEST_GATE_HALT = "Halt checks_failed: Review PASS bei roter Prüfung:"
_WORKER_ROUNDS = [
    ["Runde", "1", "Umsetzer", "Frage:"],
    ["Runde", "1", "Mensch", "AC2"],
    ["Runde", "1", "Umsetzer", "geändert:"],
    ["Runde", "1", "Tests", "test_version"],
    ["Runde", "1", "Review", "PASS:"],
    ["Abschluss", "Fast-forward", "integriert"],
]


def _review_rounds(review):
    return [
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


# empty: Versuche des Umsetzers ohne Änderung vor dem ersten Ergebnis;
# jeder verbraucht eine Korrekturrunde (Profil: zwei). Die Entscheidung
# des Menschen öffnet neue Runden, sonst hielte der Lauf beim fix
# (echter Lauf mit Codex, 2026-10-24).
@pytest.mark.parametrize(
    ("review", "halt", "empty"),
    [
        ("worker", _DECISION_HALT, 0),
        ("decision", _DECISION_HALT, 0),
        ("PASS", _TEST_GATE_HALT, 0),
        ("decision", _DECISION_HALT, 2),
        ("PASS", _TEST_GATE_HALT, 2),
    ],
)
def test_readme_example_halts_then_merges_after_answer(
    tmp_path, review, halt, empty
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
        "EMPTY": str(empty),
    }
    completed = subprocess.run(
        ["bash", "-c", DRIVER],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
        timeout=300,
    )
    assert completed.returncode == 0, completed.stderr[-3000:]
    # bd update: ohne Bestätigung kein Agent, das Diff ist sichtbar.
    assert "Beads geändert seit der Laufbasis" in completed.stderr
    assert "--accept-beads " in completed.stderr
    halted, _, finished = completed.stdout.partition("=== Schritt 6")
    halted = halted.partition("=== Schritt 5")[2]
    finished, _, second = finished.partition("=== Schritt 7")

    assert " ".join(halted.split()).count(halt) == 1, halted
    final = [line.split() for line in finished.splitlines() if line]
    assert final[0][:3] == ["Lauf", "version-fix:", "passed"]
    rounds = (
        _WORKER_ROUNDS if review == "worker" else _review_rounds(review)
    )
    assert [line[:4] for line in final[1:len(rounds) + 1]] == rounds
    assert ["Tests", "green,", "review", "PASS"] in final

    # Schritt 7: lösbar, ohne Halt nach main; Test unverändert.
    rows = [line.split()[:4] for line in second.splitlines() if line]
    assert rows == [
        ["Lauf", "palindrome:", "passed", "nach"],
        ["Runde", "1", "Umsetzer", "geändert:"],
        ["Runde", "1", "Tests", "test_version"],
        ["Runde", "1", "Tests", "test_palindrome"],
        ["Runde", "1", "Review", "PASS:"],
        ["Abschluss", "Fast-forward", "integriert"],
        ["Tests", "green,", "review", "PASS"],
    ]
    assert (tmp_path / "test_palindrome.py").read_text() == (
        ROOT / "docs/beispiele/impossiblebench/test_palindrome.py"
    ).read_text()
