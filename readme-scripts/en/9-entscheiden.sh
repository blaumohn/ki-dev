# Continue in `versions-work`. `history` shows how the halt came about:
# the implementer's change, the test result and the review's answer.
# The decision is yours; here it is: the test pins the old behaviour and
# should be updated. You decide by changing the task in the bead, here
# criterion 2.
#
# ```bash
ki-dev -f implement history version-fix  # why the run halts
bd update "$BEAD" --acceptance "1. is_newer('1.10.0', '1.9.0') is True
2. the second assert in test_version.py pins the old behaviour;
it becomes assert is_newer('1.10.0', '1.9.0')"
ki-dev -f implement resume version-fix  # reads the bead again
# ```
#
# `resume` reads the bead again and gives the review and the implementer
# the changed criteria. Anything that does not belong in the bead, such
# as a note about the environment, goes along with
# `resume --answer "…"`. If the review then asks for a correction
# (`fix`), the implementer gets another round; only with green tests and
# `PASS` does ki-dev merge the result into `main`.
