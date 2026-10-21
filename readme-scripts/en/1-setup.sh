# Needs Python ≥ 3.12, git ≥ 2.32, make, Go and a C compiler:
# `make setup` builds [Beads](https://github.com/steveyegge/beads) `bd`
# from source into the project venv, a few minutes the first time, needs
# network.
#
# ```bash
git clone https://github.com/blaumohn/ki-dev.git ki-dev
cd ki-dev
make setup                          # venv with ki-dev and bd
export PATH="$PWD/.venv/bin:$PATH"  # ki-dev and bd for the steps below
make demo
# ```
#
# `make demo` plays the example through with placeholder agents (mock):
# the review first asks for a correction (`fix`) and accepts round 2
# (`PASS`); `passed`: the result is fast-forwarded onto `main`, its
# commits listed below. The mocks only show the control flow, not an
# agent's work.
