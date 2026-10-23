# Continue in `versions-work`. `history` now shows the whole run
# including your decision; the target repo `versions` holds the final
# commit.
#
# ```bash
ki-dev -f implement history version-fix            # rounds, tests, review, finish
git -C ../versions log -1 --stat --format=%s main  # final commit on main
git -C ../versions show main:version.py            # corrected file
# ```
#
# ki-dev prints its messages in German: `Runde` is round, `Umsetzer`
# the implementer, `Mensch` the human, `geändert` changed, `bestanden`
# passed, `fehlgeschlagen` failed. The `Tests` lines are the result of
# `test_version.py`, which ki-dev runs after each implementation step;
# `Mensch` is your decision from step 5.
