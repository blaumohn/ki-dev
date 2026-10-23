# Weiter in `calc-work`. `history` fasst den Lauf aus seinen
# gespeicherten Zwischenständen zusammen; den Abschluss-Commit trägt das
# Ziel-Repo `calc`.
#
# ```bash
ki-dev -f implement history add-fix  # Runden, Tests, Review, Abschluss
git -C ../calc log -1 --format=%s    # Abschluss-Commit auf main
git -C ../calc show main:add.py      # korrigierte Datei auf main
# ```
#
# Die `Tests`-Zeile ist das Ergebnis von `test_add.py`, das ki-dev vor dem
# Review ausführt. Antwortet das Review `fix`, folgt eine weitere Runde
# mit dem Befund.
