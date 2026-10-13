# For development on ki-dev: separate runtime venv and a symlink in
# `~/.local/bin` (honors XDG_DATA_HOME).
# Finish active and paused runs before each update.
# Details: [self-development runbook (German)](docs/self-development.de.md).
#
# ```bash
make setup-runtime
export PATH="$HOME/.local/bin:$PATH"
ki-dev --help
# ```
