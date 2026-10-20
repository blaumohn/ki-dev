# Continue in `calc-work`:
#
# ```bash
ki-dev -f implement "$BEAD" --run-id add-fix  # flow implement, profile default
ki-dev -f implement status add-fix            # where the run stands
# ```
#
# With the placeholders `019a…` and `b3f1…` the run halts before the
# first agent call; for a real run put your own session IDs into the
# profile. After a halt, `ki-dev -f implement resume add-fix` continues
# the run, with `--answer` when the halt asks for one.
