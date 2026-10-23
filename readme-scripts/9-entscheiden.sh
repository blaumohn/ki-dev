# Weiter in `versions-work`. `history` zeigt, wie es zum Halt kam:
# Änderung des Umsetzers, Testergebnis und Antwort des Reviews. Die
# Entscheidung liegt bei dir; hier lautet sie: Der Test hält das alte
# Verhalten fest und soll angepasst werden. Du entscheidest, indem du
# den Auftrag im Bead änderst, hier Kriterium 2.
#
# ```bash
ki-dev -f implement history version-fix  # warum der Lauf hält
bd update "$BEAD" --acceptance "1. is_newer('1.10.0', '1.9.0') is True
2. the second assert in test_version.py pins the old behaviour;
it becomes assert is_newer('1.10.0', '1.9.0')"
ki-dev -f implement resume version-fix  # liest den Bead neu
# ```
#
# `resume` liest den Bead neu und gibt Review und Umsetzer die
# geänderten Kriterien. Was nicht in den Bead gehört, etwa ein Hinweis
# zur Umgebung, gibst du mit `resume --answer "…"` mit. Verlangt das
# Review daraufhin eine Korrektur (`fix`), folgt eine weitere Runde des
# Umsetzers; erst mit grünen Tests und `PASS` übernimmt ki-dev das
# Ergebnis nach `main`.
