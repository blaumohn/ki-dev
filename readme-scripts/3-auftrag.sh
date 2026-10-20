# Weiter im Terminal aus [Schritt 0](#0-einrichten-ohne-agenten-ausprobieren):
# ein Wegwerf-Repo `calc` mit dem Bug, daneben der Arbeits-Worktree
# `calc-work` der Agenten mit dem Auftrag.
#
# ```bash
cd "$(mktemp -d)" && git init -q -b main calc && cd calc
cat >add.py <<'EOF'
def add(a, b):
    return a - b
EOF
cat >test_add.py <<'EOF'
from add import add

assert add(2, 3) == 5
EOF
printf '.ki-dev/\n.beads.gate.lock\n' >>.git/info/exclude  # saubere Worktrees
git add . && git commit -q -m "add()"
git worktree add -q -b work ../calc-work && cd ../calc-work
bd init --quiet --prefix calc --stealth --non-interactive
BEAD="$(bd create "add() does not add" \
  --description "add(2, 3) returns -1" \
  --design "fix add.py; do not change test_add.py" \
  --acceptance "add(2, 3) == 5 and add(-1, 1) == 0" \
  --silent)"
echo "$BEAD"
# ```
#
# `$BEAD` ist die ID des Auftrags, etwa `calc-7k2`. `.ki-dev/` (Profil,
# Läufe) und die Sperrdatei von Beads bleiben außerhalb von git: ki-dev
# verlangt saubere Worktrees.
