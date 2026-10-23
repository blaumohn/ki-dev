# The first run needs network access and takes a few minutes to
# build Beads.
#
# ```bash
git clone https://github.com/blaumohn/ki-dev.git ki-dev
cd ki-dev
make setup                          # venv with ki-dev and bd
export PATH="$PWD/.venv/bin:$PATH"  # ki-dev and bd for the steps below
# ```
