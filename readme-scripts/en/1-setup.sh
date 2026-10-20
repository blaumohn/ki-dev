# The demo creates a throwaway repo with a task and a profile; a mock
# implementer and a mock review (`fix`, then `PASS`) play through the
# example without provider access. Status line and output come from
# `make readme-check`, the setup in an empty container.
#
# Needs Python ≥ 3.12, git ≥ 2.32, make, Go and a C compiler:
# `make setup` builds [Beads](https://github.com/steveyegge/beads) `bd`
# from source into the project venv (a few minutes the first time,
# needs network). `$REPLACE_WITH_REPOSITORY_URL` = this repo's clone URL.
#
# ```bash
git clone "$REPLACE_WITH_REPOSITORY_URL" ki-dev
cd ki-dev
make setup
make demo
# ```
#
# `round_id: 2`: one correction round. `passed`: the mock review
# accepted, the result is fast-forwarded onto `main`. The mocks only
# write a line of text; the demo shows the control flow, not an agent's
# work.
