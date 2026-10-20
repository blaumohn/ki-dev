# Continue in the terminal from [step 0](#0-set-up-try-it-without-agents):
# a throwaway repo `calc` with the bug, next to it the agents' worktree
# `calc-work` with the task.
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
printf '.ki-dev/\n.beads.gate.lock\n' >>.git/info/exclude  # clean worktrees
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
# `$BEAD` is the task ID, e.g. `calc-7k2`. `.ki-dev/` (profile, runs) and
# the Beads lock file stay out of git: ki-dev requires clean worktrees.
