# Weiter in `app-work`. `history` zeigt jetzt den ganzen Lauf mit
# deiner Entscheidung; den Abschluss-Commit trägt das Ziel-Repo `app`.
#
# ```bash
ki-dev -f implement history version-fix       # Runden, Tests, Review, Abschluss
git -C ../app log -1 --stat --format=%s main  # Abschluss-Commit auf main
git -C ../app show main:version.py            # korrigierte Datei
# ```
#
# Die `Tests`-Zeilen sind das Ergebnis von `test_version.py`, das `implement`
# nach jeder Umsetzung ausführt; `Mensch` ist deine Entscheidung aus
# Schritt 5. `Offen` nennt Beobachtungen des Reviews: Sie halten den Abschluss
# nicht auf, brauchen aber vor `bd close` deine Entscheidung. Der Auszug ist
# gekürzt (`…`); `history` zeigt dazu die Antworten auf die Prüffragen.
