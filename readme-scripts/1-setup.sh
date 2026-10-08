# Ohne Anbieterzugang, mit Mock-Adaptern. Voraussetzungen: Python ≥ 3.12
# (mit `venv`), git ≥ 2.32, make, Go und ein C-Compiler. `make setup` legt
# venv, ki-dev und [Beads](https://github.com/steveyegge/beads) `bd` (Version
# aus `src/ki_dev/tool-versions.json`) im Projekt an, außerhalb ändert es
# nichts. `$REPLACE_WITH_REPOSITORY_URL` steht für die Klon-Adresse dieses
# Repositorys; sie steht nach der Veröffentlichung fest.
#
# ```bash
git clone "$REPLACE_WITH_REPOSITORY_URL" ki-dev
cd ki-dev
make setup
make demo
# ```
#
# ```text
# {
#   "run_id": "demo",
#   "status": "passed",
#   "phase": "passed",
#   "round_id": 2,
#   "detail": null,
#   "operation_id": null
# }
#
# 8ef6356 Geprüfter Abschluss (Demo)
# 5c02782 start
# ```
#
# Der Mock-Reviewer antwortet erst `fix` (Urteil `CHANGES`), dann `PASS`.
# Der Lauf nimmt also die Rückkante einmal (`round_id: 2`), friert das
# geprüfte Ergebnis ein und integriert es per Fast-forward. Die
# Konfiguration schreibt das Demo-Skript nach `lauf.json`.
