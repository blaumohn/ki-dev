# Weiter in `app-work`. `history` zeigt, wer den Lauf angehalten hat
# und warum: `worker`, `review` oder Test-Tor. Du entscheidest, indem
# du den Bead änderst; hier soll der Test das neue Verhalten prüfen,
# also wird Kriterium 2 neu gefasst.
#
# ```bash
ki-dev -f implement history version-fix  # warum der Lauf hält
bd update "$BEAD" --acceptance "1. is_newer('1.10.0', '1.9.0') is True
2. the second assert in test_version.py pins the old behaviour;
it becomes assert is_newer('1.10.0', '1.9.0')"
ki-dev -f implement resume version-fix  # liest den Bead neu
# ```
#
# - `resume` liest den Bead neu und setzt dort fort, wo der Lauf hielt;
#   hier prüft zuerst das Review mit den geänderten Kriterien.
# - Was nicht in den Bead gehört, etwa ein Hinweis zur Umgebung, gibst
#   du mit `resume --answer "…"` mit.
