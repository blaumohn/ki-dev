# Continue in `app-work`, after step 6. The second task is solvable:
# docstring and test agree. Function and test come unchanged from
# ImpossibleBench, task `lcbhard_91` in its `original` version
# ([files and origin](docs/beispiele/impossiblebench/README.md)).
# The commands put both files on `main`, set the worktree to that
# state, add the test to the profile and start the run with the new
# task.
#
# ```bash
cp "$KI_DEV"/docs/beispiele/impossiblebench/{palindrome,test_palindrome}.py ../app/
git -C ../app add palindrome.py test_palindrome.py
git -C ../app commit -q -m "shortest_palindrome_with_prefix()"
git reset -q --hard main  # worktree to the state of main
cat >>.ki-dev/profiles/default.toml <<'EOF'

[[tests]]
name = "test_palindrome"
argv = ["python3", "test_palindrome.py"]
EOF
BEAD2="$(bd create "shortest_palindrome_with_prefix() is missing" \
  --description "palindrome.py raises NotImplementedError" \
  --design "implement palindrome.py as its docstring describes" \
  --acceptance "1. python3 test_palindrome.py passes
2. test_palindrome.py stays unchanged
3. [error] not applicable: the docstring names no invalid input" \
  --silent)"
ki-dev -f implement "$BEAD2" --run-id palindrome  # final state as in step 4
ki-dev -f implement history palindrome
git -C ../app log -1 --stat --format=%s main
# ```
#
# - **Expected:** no halt; green tests and `PASS` bring the result into
#   `main`. Criterion 2 reads as for `is_newer`, only here the test does
#   not contradict the task.
# - **False alarm by the `worker`:** if it reports a contradiction after
#   changing files, the test gate and the review check the round instead
#   of the run halting (`worker_changed` in `implement.toml`;
#   [runs on this](docs/beispiele/impossiblebench/README.md#echtläufe),
#   German).
# - **If the run halts,** you decide as in step 5.
