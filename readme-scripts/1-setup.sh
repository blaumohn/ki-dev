# Die Demo legt ein Wegwerf-Repo mit Auftrag und Profil an; Mock-Umsetzer
# und Mock-Review (`fix`, dann `PASS`) spielen das Beispiel ohne
# Anbieterzugang durch. Statuszeile und Ausgabe stammen aus
# `make readme-check`, der Einrichtung im leeren Container.
#
# Braucht Python ≥ 3.12, git ≥ 2.32, make, Go und einen C-Compiler:
# `make setup` baut [Beads](https://github.com/steveyegge/beads) `bd` aus
# dem Quellcode ins Projekt-venv (beim ersten Mal einige Minuten, mit Netz).
#
# ```bash
git clone https://github.com/blaumohn/ki-dev.git ki-dev
cd ki-dev
make setup
make demo
# ```
#
# `round_id: 2`: eine Korrekturrunde. `passed`: das Mock-Review hat
# akzeptiert, das Ergebnis liegt per Fast-Forward auf `main`. Die Mocks
# schreiben nur eine Textzeile; die Demo zeigt die Steuerung, nicht die
# Arbeit eines Agenten.
