# Wer ki-dev mit ki-dev weiterentwickelt, installiert es getrennt vom
# Quellbaum: eigenes venv, Symlink in `~/.local/bin`. Vor einem Update
# laufende Läufe abschließen ([Details](docs/self-development.de.md)).
#
# ```bash
make setup-runtime
export PATH="$HOME/.local/bin:$PATH"
ki-dev --help
# ```
