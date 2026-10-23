# In the ki-dev clone after the [setup](README.en.md#1-set-up). The demo
# runs a separate task with scripted answers, without model access: a
# placeholder appends to `MOCK.md`, the review asks for a correction and
# accepts round 2.
#
# ```bash
make demo
# ```
#
# The history comes from `ki-dev -f implement history`, as in
# [step 6](README.en.md#6-check-the-result) of the minimal example. The
# printed run directory contains the log and intermediate results. The
# demo shows the control flow with scripted answers; what an agent
# achieves is shown by the run in the minimal example.
