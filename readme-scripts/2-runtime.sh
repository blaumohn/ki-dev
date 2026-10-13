# Für Entwicklung an ki-dev: separates Betriebs-venv und Symlink in
# `~/.local/bin` (XDG_DATA_HOME wird berücksichtigt).
# Vor jedem Update aktive und pausierte Läufe abschließen.
# Details: [Entwicklung am eigenen Repo](docs/self-development.de.md).
#
# ```bash
make setup-runtime
export PATH="$HOME/.local/bin:$PATH"
ki-dev --help
# ```
