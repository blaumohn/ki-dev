# To develop ki-dev with ki-dev, install it apart from the source tree,
# also in the folder `ki-dev`; finish running jobs before an update
# ([details, German](docs/self-development.de.md)).
#
# ```bash
make setup-runtime                    # venv + ~/.local/bin/ki-dev
export PATH="$HOME/.local/bin:$PATH"
ki-dev --help
# ```
