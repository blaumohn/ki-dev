# In the same terminal as the setup. The commands create a throwaway
# repo with the bug: `calc` holds the target branch `main`, the agents
# work in the worktree `calc-work`. `bd create` stores problem, design
# and acceptance criteria as the task; `implement` reads these fields.
#
# ```bash
cd "$(mktemp -d)"
git init -q -b main calc && cd calc  # throwaway repo
git config user.name calc  # identity for this throwaway repo only
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
  >>.git/info/exclude  # run data, Python cache
git add . && git commit -q -m "add()"
git worktree add -q -b work ../calc-work  # the agents' worktree
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
# `$BEAD` is the task ID, e.g. `calc-7k2`.
