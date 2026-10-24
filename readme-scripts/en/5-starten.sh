# Continue in `versions-work`. ki-dev now calls the agents; depending on
# the model this takes seconds to minutes. With `-v`, ki-dev shows state
# changes and agent output live.
#
# ```bash
ki-dev -f implement "$BEAD" --run-id version-fix  # profile default
# ```
#
# The review's answer determines the next transition:
#
# | Review answer | ki-dev's response |
# |---|---|
# | `fix` | Send findings to `worker`; halt for you after the two correction rounds set in the profile. |
# | `PASS` | With green tests, prepare the final commit and fast-forward into `main`; with failing tests, halt. |
# | `decision` | Halt for your decision; continue under [Decide](#5-decide). |
#
# The end state follows as JSON. A halt for you is expected:
# `"status": "waiting_decision"` if the review asks for a decision,
# otherwise `"paused_interactive"` with the reason in `detail`:
# `checks_failed` if the review answered `PASS` despite red tests, or the
# used-up correction rounds if it answered `fix`. In every case `main`
# stays unchanged ([halting and resuming](docs/ausfuehrer.de.md), German).
