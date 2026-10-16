# Stage 2 through the public CLI: `ki-dev -f implement` with a mock
# worker and a mock review (`PASS`) against a throwaway repository with
# `add.py` (wrong: `a - b`) and a fixed `test_add.py`. No provider
# access; needs git and `bd` from `make setup`. The controls check the
# test itself: the oracle is red for `a - b` and green for `a + b`; a
# collection error does not count as a red test; green tests + PASS
# integrate. The core case is red today and marked `xfail(strict=True)`;
# `--runxfail` shows the failure:
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
# Shortened; the hashes change on every run. The run integrated into
# `main` despite red tests. Without `--runxfail` the same command
# reports `4 passed, 1 xfailed`.
