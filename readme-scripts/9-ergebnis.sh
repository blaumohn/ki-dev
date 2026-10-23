# Weiter in `versions-work`. `history` zeigt jetzt den ganzen Lauf mit
# deiner Entscheidung; den Abschluss-Commit trägt das Ziel-Repo `versions`.
#
# ```bash
ki-dev -f implement history version-fix            # Runden, Tests, Review, Abschluss
git -C ../versions log -1 --stat --format=%s main  # Abschluss-Commit auf main
git -C ../versions show main:version.py            # korrigierte Datei
# ```
#
# Die `Tests`-Zeilen sind das Ergebnis von `test_version.py`, das ki-dev
# nach jeder Umsetzung ausführt; `Mensch` ist deine Entscheidung aus
# Schritt 5.
