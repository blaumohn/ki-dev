# Continue in `app-work`. `history` shows who halted the run and why:
# `worker`, `review` or the test gate. You decide by changing the bead;
# here the test should check the new behaviour, so criterion 2 is
# rewritten.
#
# ```bash
ki-dev -f implement history version-fix  # why the run halts
bd update "$BEAD" --acceptance "1. is_newer('1.10.0', '1.9.0') is True
2. the second assert in test_version.py pins the old behaviour;
it becomes assert is_newer('1.10.0', '1.9.0')"
ki-dev -f implement resume version-fix || true  # starts nothing, shows the beads diff
STAND=$(bd vc status --json | sed -n 's/.*"commit": "\(.*\)".*/\1/p')
ki-dev -f implement resume version-fix --accept-beads "$STAND"
# ```
#
# - If the beads state differs from the run base, `resume` starts no
#   agent, shows the diff and waits for you to confirm exactly this
#   state. The state is also in the output.
# - `resume` reads the bead again and continues where the run halted;
#   here the review checks first, with the changed criteria.
# - Anything that does not belong in the bead, such as a note about the
#   environment, goes along with `resume --answer "…"`.
