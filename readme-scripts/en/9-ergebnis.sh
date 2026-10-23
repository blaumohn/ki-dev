# Continue in `calc-work`. `history` summarizes the run from its saved
# intermediate results; the target repo `calc` holds the final commit.
#
# ```bash
ki-dev -f implement history add-fix  # rounds, tests, review, finish
git -C ../calc log -1 --format=%s    # final commit on main
git -C ../calc show main:add.py      # corrected file on main
# ```
#
# ki-dev prints its messages in German: `Runde` is round, `Umsetzer`
# the implementer, `geändert` changed, `bestanden` passed. The `Tests`
# line is the result of `test_add.py`, which ki-dev runs before the
# review. If the review answers `fix`, another round follows with the
# finding.
