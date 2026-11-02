# In the same terminal as the setup. The commands first create the repo
# being worked on, a throwaway repo with code and tests: `app` holds the
# target branch `main`, the agents work in the worktree `app-work`. Then
# `bd create` stores the run's input: the task with problem, design and
# acceptance criteria.
#
# ```bash
KI_DEV="$PWD"  # ki-dev clone; step 7 takes its files from there
cd "$(mktemp -d)"
git init -q -b main app && cd app  # throwaway repo
git config user.name app  # identity for this throwaway repo only
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
  >>.git/info/exclude  # profiles, Python cache
git add . && git commit -q -m "is_newer()"
git worktree add -q -b work ../app-work  # the agents' worktree
cd ../app-work
bd init --quiet --prefix app --stealth --non-interactive
BEAD="$(bd create "is_newer() compares versions as text" \
  --description "is_newer('1.10.0', '1.9.0') returns False" \
  --design "fix version.py" \
  --acceptance "1. is_newer('1.10.0', '1.9.0') is True
2. test_version.py stays unchanged
3. [error] not applicable: versions here are always well-formed" \
  --silent)"
echo "$BEAD"
# ```
#
# `$BEAD` is the task ID, e.g. `app-7k2`. Criterion 1 asks for
# the numeric comparison; the second line of `test_version.py` still
# checks the text comparison, and criterion 2 forbids changing it. Only
# a human can resolve this contradiction; the
# [example](#minimal-example) is built for that. Criteria are numbered,
# and one names the failure case with `[error]` or, as here, why none
# applies; otherwise the run does not start. The solvable second
# task comes in [step 7](#7-second-task-solvable).
