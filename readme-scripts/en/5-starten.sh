# ```bash
ki-dev -f implement "$BEAD"
ki-dev -f implement status RUN_ID
ki-dev -f implement resume RUN_ID
# ```
#
# Flow `implement` with the profile `default` from step 2; `status` shows
# where the run is, `resume` continues after a halt. `RUN_ID` is in the
# output of the first command (`run_id`).
