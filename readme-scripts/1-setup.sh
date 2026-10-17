# Die Demo legt ein Wegwerf-Repo mit Auftrag und Profil an; Mock-Umsetzer
# und Mock-Review (`fix`, dann `PASS`) spielen das Beispiel ohne
# Anbieterzugang durch. Die Statuszeile oben gilt der Einrichtung im
# leeren Container.
#
# Braucht Python ≥ 3.12, git ≥ 2.32, make, Go und einen C-Compiler:
# `make setup` baut [Beads](https://github.com/steveyegge/beads) `bd` aus
# dem Quellcode ins Projekt-venv (beim ersten Mal einige Minuten, mit Netz).
# `$REPLACE_WITH_REPOSITORY_URL` = Klon-Adresse dieses Repos.
#
# ```bash
git clone "$REPLACE_WITH_REPOSITORY_URL" ki-dev
cd ki-dev
make setup
make demo
# ```
#
# Ausgabe (gekürzt, Hashes wechseln):
#
# ```text
# {
#   "run_id": "demo",
#   "status": "passed",
#   "round_id": 2,
#   "detail": "Fast-forward integriert"
# }
#
# ad543c6 Geprüfter Abschluss (Demo)
# 091d542 start
# ```
#
# `round_id: 2`: eine Korrekturrunde. `passed`: das Mock-Review hat
# akzeptiert, das Ergebnis liegt per Fast-Forward auf `main`. Die Mocks
# schreiben nur eine Textzeile; die Demo zeigt die Steuerung, nicht die
# Arbeit eines Agenten.
