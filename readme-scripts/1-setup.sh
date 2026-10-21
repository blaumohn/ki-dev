# Braucht Python ≥ 3.12, git ≥ 2.32, make, Go und einen C-Compiler:
# `make setup` baut [Beads](https://github.com/steveyegge/beads) `bd` aus
# dem Quellcode ins Projekt-venv, beim ersten Mal einige Minuten, mit Netz.
#
# ```bash
git clone https://github.com/blaumohn/ki-dev.git ki-dev
cd ki-dev
make setup                          # venv mit ki-dev und bd
export PATH="$PWD/.venv/bin:$PATH"  # ki-dev und bd für die Schritte unten
make demo
# ```
#
# `make demo` spielt das Beispiel mit Platzhalter-Agenten (Mock) durch:
# Das Review verlangt erst eine Korrektur (`fix`) und nimmt Runde 2 an
# (`PASS`); `passed`: Das Ergebnis liegt per Fast-Forward auf `main`,
# darunter dessen Commits. Die Mocks zeigen nur die Steuerung, nicht die
# Arbeit eines Agenten.
