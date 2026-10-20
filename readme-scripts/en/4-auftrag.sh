# In the ki-dev clone after [Try it](#try-it-without-agents): `bd` lives
# in the project venv. A throwaway repo `calc` with the bug, next to it
# the agents' worktree `calc-work` with its own Beads project and the
# profile from step 2. `.ki-dev/` (profile, runs) and the Beads lock file
# stay out of git: ki-dev requires clean worktrees.
#
# ```bash
export PATH="$PWD/.venv/bin:$PATH"
PROFILE="$PWD/docs/beispiele/default.toml"
cd "$(mktemp -d)" && git init -q -b main calc && cd calc
git config user.name calc && git config user.email calc@example.invalid
printf 'def add(a, b):\n    return a - b\n' >add.py
printf 'from add import add\n\nassert add(2, 3) == 5\n' >test_add.py
printf '.ki-dev/\n.beads.gate.lock\n' >>.git/info/exclude
git add . && git commit -q -m "add()"
git worktree add -q -b work ../calc-work && cd ../calc-work
mkdir -p .ki-dev/profiles && cp "$PROFILE" .ki-dev/profiles/default.toml
bd init --quiet --prefix calc --stealth --non-interactive
BEAD="$(bd create "add() does not add" \
  --description "add(2, 3) returns -1" \
  --design "fix add.py; do not change test_add.py" \
  --acceptance "add(2, 3) == 5 and add(-1, 1) == 0" \
  --silent)"
echo "$BEAD"
# ```
#
# `$BEAD` is the task ID, e.g. `calc-7k2`; step 4 uses it in the same
# terminal, in `calc-work`.
