# **Wann ist das Test-Tor fertig?** Wenn dieser Test grün ist. Er startet
# `ki-dev -f implement` gegen ein Wegwerf-Repo mit falschem `add.py`
# (`a - b`); die Tests sind rot, das Mock-Review sagt trotzdem `PASS`.
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
# Heute landet das Ergebnis trotz roter Tests auf `main`. Die vier grünen
# Fälle prüfen den Test selbst, etwa: grüne Tests plus `PASS` integrieren.
