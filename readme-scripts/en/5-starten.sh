# Continue in `calc-work`. ki-dev now calls the agents; depending on
# the model this takes seconds to minutes. With `-v`, ki-dev shows state
# changes and agent output live.
#
# ```bash
ki-dev -f implement "$BEAD" --run-id add-fix  # profile default
# ```
#
# The end state follows as JSON, after success with
# `"status": "passed"`. If the run halts, `detail` names the reason;
# `ki-dev -f implement resume add-fix` continues afterwards
# ([halting and resuming](docs/ausfuehrer.de.md), German).
