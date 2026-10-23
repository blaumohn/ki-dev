# Im selben Terminal wie die Einrichtung. Die Befehle legen ein
# Wegwerf-Repo mit dem Fehler an: `calc` trägt den Zielbranch `main`,
# im Worktree `calc-work` arbeiten die Agenten. `bd create` speichert
# Problem, Entwurf und Abnahmekriterien als Auftrag; `implement` liest
# diese Felder.
#
# ```bash
cd "$(mktemp -d)"
git init -q -b main calc && cd calc  # Wegwerf-Repo
git config user.name calc  # Identität nur für dieses Wegwerf-Repo
git config user.email calc@example.invalid
cat >add.py <<'EOF'
def add(a, b):
    return a - b
EOF
cat >test_add.py <<'EOF'
from add import add

assert add(2, 3) == 5
EOF
printf '%s\n' .ki-dev/ .beads.gate.lock __pycache__/ \
  >>.git/info/exclude  # Laufdaten, Python-Cache
git add . && git commit -q -m "add()"
git worktree add -q -b work ../calc-work  # Arbeits-Worktree der Agenten
cd ../calc-work
bd init --quiet --prefix calc --stealth --non-interactive
BEAD="$(bd create "add() does not add" \
  --description "add(2, 3) returns -1" \
  --design "fix add.py; do not change test_add.py" \
  --acceptance "add(2, 3) == 5 and add(-1, 1) == 0" \
  --silent)"
echo "$BEAD"
# ```
#
# `$BEAD` ist die ID des Auftrags, etwa `calc-7k2`.
