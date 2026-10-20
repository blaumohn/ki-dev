# In the ki-dev clone after [Try it](#try-it-without-agents): `bd` lives
# in the project venv, the task goes into a throwaway repo with its own
# Beads project.
#
# ```bash
export PATH="$PWD/.venv/bin:$PATH"
cd "$(mktemp -d)" && git init -q
bd init --quiet --prefix calc --stealth --non-interactive
BEAD="$(bd create "add() does not add" \
  --description "add(2, 3) returns -1" \
  --design "fix add.py; do not change test_add.py" \
  --acceptance "add(2, 3) == 5 and add(-1, 1) == 0" \
  --silent)"
echo "$BEAD"
# ```
#
# `$BEAD` is the task ID, e.g. `calc-7k2`; step 4 uses it.
