# Im selben Terminal wie die Einrichtung. Die Befehle legen zuerst das
# Repo an, an dem gearbeitet wird, ein Wegwerf-Repo mit Code und Tests:
# `app` trägt den Zielbranch `main`, im Worktree `app-work` arbeiten die
# Agenten. Danach speichert `bd create` die Eingabe des Laufs: den
# Auftrag mit Problem, Entwurf und Abnahmekriterien.
#
# ```bash
KI_DEV="$PWD"  # ki-dev-Klon; Schritt 7 holt daraus seine Dateien
cd "$(mktemp -d)"
git init -q -b main app && cd app  # Wegwerf-Repo
git config user.name app  # Identität nur für dieses Wegwerf-Repo
git config user.email app@example.invalid
cat >version.py <<'EOF'
def is_newer(a, b):
    return a > b
EOF
cat >test_version.py <<'EOF'
from version import is_newer

assert is_newer("2.0.0", "1.9.9")
assert not is_newer("1.10.0", "1.9.0")
EOF
printf '%s\n' .ki-dev/ .beads.gate.lock __pycache__/ \
  >>.git/info/exclude  # Laufdaten, Python-Cache
git add . && git commit -q -m "is_newer()"
git worktree add -q -b work ../app-work  # Arbeits-Worktree der Agenten
cd ../app-work
bd init --quiet --prefix app --stealth --non-interactive
BEAD="$(bd create "is_newer() compares versions as text" \
  --description "is_newer('1.10.0', '1.9.0') returns False" \
  --design "fix version.py" \
  --acceptance "1. is_newer('1.10.0', '1.9.0') is True
2. test_version.py stays unchanged" \
  --silent)"
echo "$BEAD"
# ```
#
# `$BEAD` ist die ID des Auftrags, etwa `app-7k2`. Kriterium 1
# verlangt den Zahlenvergleich; die zweite Zeile von `test_version.py`
# prüft noch den Textvergleich, und Kriterium 2 verbietet, sie zu
# ändern. Diesen Widerspruch löst nur ein Mensch; darauf ist das
# [Beispiel](#minimalbeispiel) angelegt. Den lösbaren zweiten Auftrag
# legt [Schritt 7](#7-zweiter-auftrag-lösbar) an.
