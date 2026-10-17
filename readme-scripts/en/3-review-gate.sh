# **When is the test gate done?** When this test is green. It runs
# `ki-dev -f implement` against a throwaway repo with a wrong `add.py`
# (`a - b`); the tests are red, the mock review still says `PASS`.
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
# Today the result lands on `main` despite red tests. The four green
# cases check the test itself, e.g. green tests plus `PASS` do integrate.
