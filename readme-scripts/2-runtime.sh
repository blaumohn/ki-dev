# Wer ki-dev mit ki-dev weiterentwickelt, installiert es getrennt vom
# Quellbaum, ebenfalls im Ordner `ki-dev`; vor einem Update laufende Läufe
# abschließen ([Details](docs/self-development.de.md)).
#
# ```bash
make setup-runtime                    # venv + ~/.local/bin/ki-dev
export PATH="$HOME/.local/bin:$PATH"
ki-dev --help
# ```
