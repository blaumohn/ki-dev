# Continue in `app-work`. `history` now shows the whole run
# including your decision; the target repo `app` holds the final
# commit.
#
# ```bash
ki-dev -f implement history version-fix       # rounds, tests, review, finish
git -C ../app log -1 --stat --format=%s main  # final commit on main
git -C ../app show main:version.py            # corrected file
# ```
#
# ki-dev prints its messages in German: `Runde` is round, `Umsetzer`
# the implementer, `Mensch` the human, `geändert` changed, `bestanden`
# passed, `fehlgeschlagen` failed. The `Tests` lines are the result of
# `test_version.py`, which `implement` runs after each
# implementation step;
# `Mensch` is your decision from step 5. `Offen` (open) names the review's
# observations (`Beobachtungen`): they do not hold up the commit, but need
# your decision before `bd close`. The excerpt is shortened (`…`); `history`
# also shows the answers to the review questions.
