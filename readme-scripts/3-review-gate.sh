# Stufe 2 über die öffentliche CLI: `ki-dev -f implement` mit
# Mock-Worker und Mock-Review (`PASS`) gegen ein Wegwerf-Repo mit
# `add.py` (falsch: `a - b`) und festem `test_add.py`. Kein
# Anbieterzugang; braucht git und `bd` aus `make setup`. Die Kontrollen
# prüfen den Test selbst: Orakel rot bei `a - b`, grün bei `a + b`; ein
# Collection-Fehler zählt nicht als roter Test; grüne Tests + PASS
# integrieren. Der Kernfall ist heute rot und als `xfail(strict=True)`
# markiert; `--runxfail` zeigt den Fehlschlag:
#
# ```bash
.venv/bin/pytest -q --runxfail tests/test_review_gate_cli.py
# ```
#
# ```text
# E   tests.test_review_gate_cli.IntegratedDespiteRedTests: 3e696bb -> d14aedd: Fast-forward integriert
# FAILED tests/test_review_gate_cli.py::test_red_tests_and_review_pass_do_not_integrate
# 1 failed, 4 passed
# ```
#
# Gekürzt; die Hashes wechseln je Lauf. Der Lauf hat trotz roter Tests
# auf `main` integriert (ek1). Ohne `--runxfail` meldet
# derselbe Befehl `4 passed, 1 xfailed`.
