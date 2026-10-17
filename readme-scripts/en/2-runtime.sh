# To develop ki-dev with ki-dev, install it apart from the source tree:
# own venv, symlink in `~/.local/bin`. Finish running jobs before an
# update ([details, German](docs/self-development.de.md)).
#
# ```bash
make setup-runtime
export PATH="$HOME/.local/bin:$PATH"
ki-dev --help
# ```
