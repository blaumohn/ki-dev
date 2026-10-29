# Continue in `app-work`. ki-dev now calls the agents; depending on
# the model this takes seconds to minutes. With `-v`, ki-dev shows state
# changes and agent output live.
#
# ```bash
ki-dev -f implement "$BEAD" --run-id version-fix  # profile default
# ```
#
# Which transition follows an answer is set in `implement.toml`:
#
# | Answer | Transition in `implement` |
# |---|---|
# | `worker` done | Run the tests from the profile, then ask `review`. |
# | `worker` with an open question | Without changes, halt for you ([Decide](#5-decide)); with changes, tests and `review` check the round. |
# | `review`: `fix` | Send findings to `worker`; halt for you after the two correction rounds set in the profile. |
# | `review`: `PASS` | With green tests, fast-forward the final commit into `main`; with failing tests, halt. |
# | `review`: `decision` | Halt for your decision. |
#
# The end state follows as JSON. A halt for you is expected; which
# part triggers it depends on the answers: `"waiting_decision"` after a
# `worker` question or a `review` `decision`, `"paused_interactive"`
# when the test gate or the round limit halts. `history` in
# [step 5](#5-decide) shows the reason; `main` stays unchanged
# ([halting and resuming](docs/ausfuehrer.de.md), German).
