# ```bash
ki-dev -f implement "$BEAD" --run-id add-fix
ki-dev -f implement status add-fix
# ```
#
# Flow `implement` with the profile `default` from step 2, run `add-fix`;
# `status` shows where it is. After a halt,
# `ki-dev -f implement resume add-fix` continues it, with `--answer` when
# the halt asks for one. With the placeholders `019a…` and `b3f1…` the
# run halts before the first agent call; for a real run put your own
# session IDs into the profile.
