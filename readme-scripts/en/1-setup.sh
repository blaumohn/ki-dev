# Offline, with mock adapters. Prerequisites: Python ≥ 3.12 (with `venv`),
# git ≥ 2.32, make, Go and a C compiler. `make setup` creates the venv,
# ki-dev and [Beads](https://github.com/steveyegge/beads) `bd` (version from
# `src/ki_dev/tool-versions.json`) inside the project and changes nothing
# outside it. `$REPLACE_WITH_REPOSITORY_URL` stands for the clone address of
# this repository; it is fixed once the repository is published.
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
# The mock reviewer answers `fix` (verdict `CHANGES`), then `PASS`: the run
# takes the back edge once (`round_id: 2`), freezes the reviewed result and
# fast-forwards it into `main`.
